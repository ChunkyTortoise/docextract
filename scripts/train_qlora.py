"""QLoRA fine-tuning script for DocExtract document classifiers.

Consumes supervised JSONL exported by the HITL correction pipeline
(GET /finetune/export?format=supervised) and fine-tunes Mistral-7B-Instruct
with 4-bit quantization (QLoRA) + LoRA adapters.

Usage
-----
# Pull training data from a running DocExtract API
python scripts/train_qlora.py \\
    --source http://localhost:8000/finetune/export \\
    --api-key $DOCEXTRACT_API_KEY \\
    --doc-type invoice \\
    --epochs 3

# Use a local JSONL file (for offline or CI testing)
python scripts/train_qlora.py \\
    --source data/train.jsonl \\
    --doc-type invoice \\
    --dry-run            # skips model loading, validates pipeline end-to-end

References
----------
- QLoRA: Dettmers et al. (2023) — https://arxiv.org/abs/2305.14314
- LoRA:  Hu et al. (2021)       — https://arxiv.org/abs/2106.09685
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — match notebook configuration
# ---------------------------------------------------------------------------

MODEL_ID = "mistralai/Mistral-7B-Instruct-v0.2"
ADAPTER_BASE = Path(__file__).parent.parent / "adapters"
REGISTRY_PATH = ADAPTER_BASE / "registry.json"

# LoRA hyperparameters (plain dict — importable without torch/peft)
LORA_CONFIG: dict[str, Any] = {
    "r": 16,              # Rank: controls adapter capacity
    "lora_alpha": 32,     # Effective scale = alpha/r = 2.0
    "target_modules": ["q_proj", "v_proj"],
    "lora_dropout": 0.1,
    "bias": "none",
}

# QLoRA quantization hyperparameters
QUANT_CONFIG: dict[str, Any] = {
    "load_in_4bit": True,
    "bnb_4bit_quant_type": "nf4",
    "bnb_4bit_compute_dtype": "float16",
    "bnb_4bit_use_double_quant": True,
}

MAX_LENGTH = 512


# ---------------------------------------------------------------------------
# Pure helpers (no ML deps — fully testable in CI)
# ---------------------------------------------------------------------------


def load_jsonl_file(path: Path) -> list[dict[str, Any]]:
    """Load JSONL records from a local file."""
    records: list[dict[str, Any]] = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def load_jsonl_url(url: str, api_key: str, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Fetch JSONL from the DocExtract export API."""
    try:
        import httpx
    except ImportError as exc:
        raise ImportError("httpx required: pip install httpx") from exc

    resp = httpx.get(url, headers={"X-API-Key": api_key}, params=params or {}, timeout=120)
    resp.raise_for_status()
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


def load_jsonl(source: str, api_key: str = "", doc_type: str | None = None) -> list[dict[str, Any]]:
    """Load supervised JSONL from a file path or HTTP URL."""
    if source.startswith("http"):
        params: dict[str, str] = {"format": "supervised", "split": "train"}
        if doc_type:
            params["doc_type"] = doc_type
        return load_jsonl_url(source, api_key, params)
    return load_jsonl_file(Path(source))


def build_training_texts(records: list[dict[str, Any]]) -> list[str]:
    """Convert supervised JSONL records to Mistral-Instruct training strings.

    Expected record format (from FineTuneExporter._to_supervised):
        {"messages": [
            {"role": "system", "content": "..."},
            {"role": "user",   "content": "..."},
            {"role": "assistant", "content": "..."}
        ]}
    """
    texts: list[str] = []
    for rec in records:
        messages = rec.get("messages", [])
        if len(messages) < 3:
            continue
        system = messages[0].get("content", "")
        user = messages[1].get("content", "")
        assistant = messages[2].get("content", "")
        # Mistral-Instruct chat template
        texts.append(f"<s>[INST] {system}\n\n{user} [/INST] {assistant} </s>")
    return texts


def load_registry(registry_path: Path = REGISTRY_PATH) -> dict[str, Any]:
    """Read the adapter registry. Returns empty registry if file missing."""
    if not registry_path.exists():
        return {"version": "1.0", "adapters": []}
    return json.loads(registry_path.read_text())


def get_adapters_by_doc_type(doc_type: str, registry_path: Path = REGISTRY_PATH) -> list[dict[str, Any]]:
    """Return all registry entries for a given doc_type, newest first."""
    registry = load_registry(registry_path)
    matches = [e for e in registry["adapters"] if e.get("doc_type") == doc_type]
    return sorted(matches, key=lambda e: e.get("trained_at", ""), reverse=True)


def update_registry(
    adapter_path: Path,
    doc_type: str,
    base_model: str,
    n_samples: int,
    training_format: str,
    eval_metrics: dict[str, Any],
    registry_path: Path = REGISTRY_PATH,
) -> dict[str, Any]:
    """Append an adapter entry to the JSON registry. Creates file if needed."""
    registry = load_registry(registry_path)
    entry: dict[str, Any] = {
        "id": f"{doc_type}_{adapter_path.name}",
        "doc_type": doc_type,
        "adapter_path": str(adapter_path),
        "base_model": base_model,
        "trained_at": datetime.utcnow().isoformat(),
        "training_format": training_format,
        "training_samples": n_samples,
        "eval_metrics": eval_metrics,
    }
    registry["adapters"].append(entry)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(registry, indent=2, default=str))
    logger.info("Registry updated: %s adapters total", len(registry["adapters"]))
    return entry


# ---------------------------------------------------------------------------
# ML training (lazy imports — only runs when not in dry-run mode)
# ---------------------------------------------------------------------------


def _load_model_and_tokenizer(model_id: str):
    """Load base model with 4-bit quantization and tokenizer."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    quant_config = BitsAndBytesConfig(
        load_in_4bit=QUANT_CONFIG["load_in_4bit"],
        bnb_4bit_quant_type=QUANT_CONFIG["bnb_4bit_quant_type"],
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=QUANT_CONFIG["bnb_4bit_use_double_quant"],
    )
    model = AutoModelForCausalLM.from_pretrained(
        model_id, quantization_config=quant_config, device_map="auto"
    )
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    tokenizer.pad_token = tokenizer.eos_token
    return model, tokenizer


def _apply_lora(model):
    """Wrap model with LoRA adapters using notebook-matched config."""
    from peft import LoraConfig, TaskType, get_peft_model, prepare_model_for_kbit_training

    model = prepare_model_for_kbit_training(model)
    lora_cfg = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=LORA_CONFIG["r"],
        lora_alpha=LORA_CONFIG["lora_alpha"],
        target_modules=LORA_CONFIG["target_modules"],
        lora_dropout=LORA_CONFIG["lora_dropout"],
        bias=LORA_CONFIG["bias"],
        inference_mode=False,
    )
    return get_peft_model(model, lora_cfg)


def _tokenize_dataset(texts: list[str], tokenizer, max_length: int = MAX_LENGTH):
    """Build a HuggingFace Dataset from training texts."""
    from datasets import Dataset

    def _encode(batch):
        return tokenizer(
            batch["text"],
            truncation=True,
            max_length=max_length,
            padding="max_length",
        )

    ds = Dataset.from_dict({"text": texts})
    return ds.map(_encode, batched=True, remove_columns=["text"])


def _run_training(model, tokenizer, dataset, output_dir: Path, epochs: int, batch_size: int):
    """Execute the training loop and save the adapter."""
    from transformers import DataCollatorForLanguageModeling, Trainer, TrainingArguments

    args = TrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=4,
        warmup_steps=10,
        learning_rate=2e-4,
        fp16=True,
        logging_steps=10,
        save_strategy="epoch",
        report_to="none",
    )
    collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=dataset,
        data_collator=collator,
    )
    trainer.train()
    model.save_pretrained(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))
    return trainer.state.log_history


# ---------------------------------------------------------------------------
# Main train() function
# ---------------------------------------------------------------------------


def train(args: argparse.Namespace) -> dict[str, Any]:
    """Run full QLoRA training pipeline. Returns the registry entry created."""
    logger.info("Loading training data from %s", args.source)
    records = load_jsonl(args.source, api_key=args.api_key, doc_type=args.doc_type)
    if not records:
        logger.error("No training records found. Exiting.")
        sys.exit(1)

    texts = build_training_texts(records)
    logger.info("Prepared %d training examples", len(texts))

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    doc_type_label = args.doc_type or "all"
    output_dir = ADAPTER_BASE / doc_type_label / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    log_history: list[dict] = []
    if not args.dry_run:
        model, tokenizer = _load_model_and_tokenizer(args.model)
        model = _apply_lora(model)
        dataset = _tokenize_dataset(texts, tokenizer)
        log_history = _run_training(model, tokenizer, dataset, output_dir, args.epochs, args.batch_size)
        final_loss = log_history[-1].get("train_loss", 0.0) if log_history else 0.0
    else:
        logger.info("[DRY RUN] Skipping model load and training.")
        final_loss = 0.0

    eval_metrics = {"train_loss": round(final_loss, 4), "training_samples": len(texts)}
    entry = update_registry(
        adapter_path=output_dir,
        doc_type=doc_type_label,
        base_model=args.model,
        n_samples=len(texts),
        training_format="qlora",
        eval_metrics=eval_metrics,
    )
    logger.info("Adapter saved to %s", output_dir)
    return entry


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QLoRA fine-tuning for DocExtract classifiers")
    parser.add_argument("--source", required=True, help="JSONL file path or API URL")
    parser.add_argument("--api-key", default="", help="DocExtract API key (for URL sources)")
    parser.add_argument("--doc-type", default=None, help="Filter training data by document type")
    parser.add_argument("--model", default=MODEL_ID, help="Base model ID on HuggingFace Hub")
    parser.add_argument("--epochs", type=int, default=3, help="Number of training epochs")
    parser.add_argument("--batch-size", type=int, default=4, help="Per-device training batch size")
    parser.add_argument("--dry-run", action="store_true", help="Parse data but skip model loading")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args(argv)
    entry = train(args)
    print(json.dumps(entry, indent=2, default=str))


if __name__ == "__main__":
    main()
