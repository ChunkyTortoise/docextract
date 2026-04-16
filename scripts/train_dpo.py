"""DPO (Direct Preference Optimization) fine-tuning script for DocExtract.

Consumes DPO-format JSONL exported by the HITL correction pipeline
(GET /finetune/export?format=dpo) and trains a preference-aligned model
using TRL's DPOTrainer.

Each HITL correction is a natural preference pair:
  chosen  = human-corrected extraction (preferred)
  rejected = model's original output (rejected)

Usage
-----
python scripts/train_dpo.py \\
    --source http://localhost:8000/finetune/export \\
    --api-key $DOCEXTRACT_API_KEY \\
    --adapter-path adapters/invoice/20260326_143022  # base adapter from QLoRA

python scripts/train_dpo.py --source data/dpo.jsonl --dry-run

References
----------
- DPO: Rafailov et al. (2023) — https://arxiv.org/abs/2305.18290
- TRL DPOTrainer — https://huggingface.co/docs/trl/dpo_trainer
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.train_qlora import (
    ADAPTER_BASE,
    MODEL_ID,
    _wandb_enabled,
    load_jsonl_file,
    load_jsonl_url,
    update_registry,
)

logger = logging.getLogger(__name__)

# DPO hyperparameters
DPO_CONFIG: dict[str, Any] = {
    "beta": 0.1,           # KL-penalty coefficient (lower = more divergence allowed)
    "learning_rate": 5e-5,
    "num_train_epochs": 1,
    "per_device_train_batch_size": 2,
    "gradient_accumulation_steps": 4,
    "max_length": 512,
    "max_prompt_length": 256,
}


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def load_dpo_jsonl(source: str, api_key: str = "", doc_type: str | None = None) -> list[dict[str, Any]]:
    """Load DPO-format JSONL from file or API."""
    if source.startswith("http"):
        params: dict[str, str] = {"format": "dpo", "split": "train"}
        if doc_type:
            params["doc_type"] = doc_type
        return load_jsonl_url(source, api_key, params)
    return load_jsonl_file(Path(source))


def build_dpo_pairs(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Convert DPO JSONL records to {prompt, chosen, rejected} dicts.

    Expected record format (from FineTuneExporter._to_dpo):
        {"prompt": "system_prompt", "chosen": "...", "rejected": "...", "doc_type": "..."}
    """
    pairs: list[dict[str, str]] = []
    for rec in records:
        prompt = rec.get("prompt", "")
        chosen = rec.get("chosen", "")
        rejected = rec.get("rejected", "")
        if prompt and chosen and rejected:
            pairs.append({"prompt": prompt, "chosen": chosen, "rejected": rejected})
    return pairs


def validate_dpo_pairs(pairs: list[dict[str, str]]) -> list[str]:
    """Return a list of validation error messages (empty = all OK)."""
    errors: list[str] = []
    for i, pair in enumerate(pairs):
        for field in ("prompt", "chosen", "rejected"):
            if not pair.get(field):
                errors.append(f"Pair {i}: missing or empty '{field}'")
        if pair.get("chosen") == pair.get("rejected"):
            errors.append(f"Pair {i}: chosen and rejected are identical")
    return errors


# ---------------------------------------------------------------------------
# ML training (lazy imports)
# ---------------------------------------------------------------------------


def _run_dpo_training(
    base_model_id: str,
    adapter_path: str | None,
    pairs: list[dict[str, str]],
    output_dir: Path,
    config: dict[str, Any],
    use_wandb: bool = False,
) -> dict[str, Any]:
    """Execute DPO training loop and save the aligned adapter."""
    import torch
    from datasets import Dataset
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from trl import DPOConfig, DPOTrainer

    tokenizer = AutoTokenizer.from_pretrained(base_model_id)
    tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        base_model_id, torch_dtype=torch.float16, device_map="auto"
    )
    if adapter_path:
        model = PeftModel.from_pretrained(model, adapter_path)
    ref_model = AutoModelForCausalLM.from_pretrained(
        base_model_id, torch_dtype=torch.float16, device_map="auto"
    )

    dataset = Dataset.from_list(pairs)

    dpo_cfg = DPOConfig(
        output_dir=str(output_dir),
        beta=config["beta"],
        learning_rate=config["learning_rate"],
        num_train_epochs=config["num_train_epochs"],
        per_device_train_batch_size=config["per_device_train_batch_size"],
        gradient_accumulation_steps=config["gradient_accumulation_steps"],
        max_length=config["max_length"],
        max_prompt_length=config["max_prompt_length"],
        report_to="wandb" if use_wandb else "none",
        logging_steps=10,
    )
    trainer = DPOTrainer(
        model=model,
        ref_model=ref_model,
        args=dpo_cfg,
        train_dataset=dataset,
        tokenizer=tokenizer,
    )
    trainer.train()
    model.save_pretrained(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))
    log_history = trainer.state.log_history
    final_loss = log_history[-1].get("train_loss", 0.0) if log_history else 0.0
    return {"dpo_loss": round(final_loss, 4)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def train_dpo(args: argparse.Namespace) -> dict[str, Any]:
    """Run DPO training pipeline. Returns the registry entry."""
    records = load_dpo_jsonl(args.source, api_key=args.api_key, doc_type=args.doc_type)
    if not records:
        logger.error("No DPO records found. Exiting.")
        sys.exit(1)

    pairs = build_dpo_pairs(records)
    errors = validate_dpo_pairs(pairs)
    if errors:
        for err in errors:
            logger.warning("Validation: %s", err)

    logger.info("Prepared %d DPO pairs (%d validation issues)", len(pairs), len(errors))

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    doc_type_label = args.doc_type or "all"
    output_dir = ADAPTER_BASE / f"{doc_type_label}_dpo" / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    use_wandb = _wandb_enabled()
    if use_wandb and not args.dry_run:
        import wandb
        wandb.init(
            project="docextract-finetune",
            name=f"dpo_{doc_type_label}_{timestamp}",
            config={**DPO_CONFIG, "model": args.model, "adapter_path": args.adapter_path},
        )
        logger.info("W&B run: %s", wandb.run.url)

    eval_metrics: dict[str, Any]
    if not args.dry_run:
        eval_metrics = _run_dpo_training(
            base_model_id=args.model,
            adapter_path=args.adapter_path,
            pairs=pairs,
            output_dir=output_dir,
            config=DPO_CONFIG,
            use_wandb=use_wandb,
        )
    else:
        logger.info("[DRY RUN] Skipping DPO model load and training.")
        eval_metrics = {"dpo_loss": 0.0}

    eval_metrics["training_samples"] = len(pairs)

    if use_wandb and not args.dry_run:
        import wandb
        if wandb.run:
            eval_metrics["wandb_url"] = wandb.run.url
            wandb.summary.update({"adapter_path": str(output_dir), **eval_metrics})
            wandb.finish()
    entry = update_registry(
        adapter_path=output_dir,
        doc_type=doc_type_label,
        base_model=args.model,
        n_samples=len(pairs),
        training_format="dpo",
        eval_metrics=eval_metrics,
    )
    logger.info("DPO adapter saved to %s", output_dir)
    return entry


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DPO fine-tuning for DocExtract")
    parser.add_argument("--source", required=True, help="DPO JSONL file path or API URL")
    parser.add_argument("--api-key", default="", help="DocExtract API key")
    parser.add_argument("--doc-type", default=None, help="Filter by document type")
    parser.add_argument("--model", default=MODEL_ID, help="Base model ID")
    parser.add_argument("--adapter-path", default=None, help="QLoRA adapter to start from")
    parser.add_argument("--dry-run", action="store_true", help="Skip model loading")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args(argv)
    entry = train_dpo(args)
    print(json.dumps(entry, indent=2, default=str))


if __name__ == "__main__":
    main()
