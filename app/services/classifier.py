"""Document type classifier using Claude tool_use (with optional local LoRA adapter)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import anthropic
from anthropic import AsyncAnthropic

from app.config import settings
from app.services.prompt_config import config as prompt_config

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

DOCUMENT_TYPES = [
    "invoice",
    "purchase_order",
    "receipt",
    "bank_statement",
    "identity_document",
    "medical_record",
    "unknown",
]

CLASSIFY_TOOL = {
    "name": "classify_document",
    "description": "Classify a document into one of the supported types",
    "input_schema": {
        "type": "object",
        "properties": {
            "document_type": {
                "type": "string",
                "enum": DOCUMENT_TYPES,
                "description": "The type of document",
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Confidence score 0-1",
            },
            "reasoning": {
                "type": "string",
                "description": "Brief reasoning for the classification",
            },
        },
        "required": ["document_type", "confidence", "reasoning"],
    },
}

# Keep for backward compat
CLASSIFY_SCHEMA = CLASSIFY_TOOL["input_schema"]

CLASSIFY_PROMPT = """Analyze this document and classify it into one of these types:
- invoice: A bill from a vendor requesting payment
- purchase_order: A buyer's order requesting goods/services
- receipt: Proof of purchase/payment
- bank_statement: Bank account transaction history
- identity_document: Passport, driver's license, national ID
- medical_record: Patient health record, visit notes, prescriptions
- unknown: Cannot determine type

Document text (first 2000 chars):
{text}

Use the classify_document tool to return your classification."""


@dataclass
class ClassificationResult:
    doc_type: str
    confidence: float
    reasoning: str


async def classify(text: str, db: AsyncSession | None = None) -> ClassificationResult:
    """Classify document type using Claude tool_use (or local LoRA adapter if enabled).

    When USE_LOCAL_ADAPTER=true: tries local adapter first; falls back to Claude if
    no adapter is registered or inference fails.
    Returns ClassificationResult with doc_type='unknown' on low confidence or error.
    Uses model router for automatic fallback on provider failures.
    """
    if settings.use_local_adapter:
        adapter_entry = _get_best_adapter()
        if adapter_entry:
            result = _predict_with_adapter(text, adapter_entry)
            if result is not None:
                return result
        logger.info("Local adapter unavailable or failed — falling back to Claude")

    from app.services.llm_tracer import trace_llm_call
    from app.services.model_router import AllModelsUnavailableError, ModelRouter

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    router = ModelRouter(
        failure_threshold=settings.circuit_breaker_failure_threshold,
        recovery_timeout=settings.circuit_breaker_recovery_seconds,
    )
    sample = text[: prompt_config.params.classify_text_limit]

    try:
        async def _classify_call(model: str) -> anthropic.types.Message:
            async with trace_llm_call(db, model, "classify") as trace_ctx:
                response = await client.messages.create(
                    model=model,
                    max_tokens=256,
                    messages=[
                        {"role": "user", "content": prompt_config.classify_prompt.format(text=sample)}
                    ],
                    tools=[CLASSIFY_TOOL],
                    tool_choice={"type": "tool", "name": "classify_document"},
                )
                trace_ctx.record_response(response)
            return response

        response, _ = await router.call_with_fallback(
            operation="classify",
            chain=settings.classification_models,
            call_fn=_classify_call,
        )

        # Find tool_use block
        result = None
        for block in response.content:
            if hasattr(block, "type") and block.type == "tool_use" and block.name == "classify_document":
                result = block.input
                break

        # Fallback to legacy text parsing if no tool_use block
        if result is None:
            result = _parse_legacy_response(response)

        if result is None:
            return ClassificationResult(doc_type="unknown", confidence=0.0, reasoning="No response")

        doc_type = result.get("document_type", "unknown")
        confidence = float(result.get("confidence", 0.0))
        reasoning = result.get("reasoning", "")

        if confidence < prompt_config.params.classification_confidence_threshold:
            doc_type = "unknown"

        return ClassificationResult(
            doc_type=doc_type,
            confidence=confidence,
            reasoning=reasoning,
        )

    except (AllModelsUnavailableError, anthropic.APIError, KeyError, IndexError) as e:
        logger.warning("Classification failed: %s", e)
        return ClassificationResult(doc_type="unknown", confidence=0.0, reasoning=str(e))


def _get_best_adapter() -> dict[str, Any] | None:
    """Return the most recent adapter entry from the registry, or None if empty."""
    try:
        from scripts.train_qlora import REGISTRY_PATH, load_registry

        registry = load_registry(REGISTRY_PATH)
        adapters = registry.get("adapters", [])
        if not adapters:
            return None
        # Prefer "all" adapters (trained on all doc types); fall back to any
        all_adapters = [a for a in adapters if a.get("doc_type") == "all"]
        candidates = all_adapters if all_adapters else adapters
        return max(candidates, key=lambda a: a.get("trained_at", ""))
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not load adapter registry: %s", e)
        return None


def _predict_with_adapter(text: str, adapter_entry: dict[str, Any]) -> ClassificationResult | None:
    """Run inference with a local LoRA adapter. Returns None on any failure."""
    try:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        adapter_path = adapter_entry["adapter_path"]
        base_model = adapter_entry.get("base_model", "mistralai/Mistral-7B-Instruct-v0.2")
        base_revision = adapter_entry.get("base_revision", "main")

        tokenizer = AutoTokenizer.from_pretrained(base_model, revision=base_revision)
        model = AutoModelForCausalLM.from_pretrained(
            base_model,
            revision=base_revision,
            torch_dtype=torch.float16,
            device_map="auto",
        )
        model = PeftModel.from_pretrained(model, adapter_path)
        model.eval()

        prompt = f"Classify the document type of this text:\n{text[:2000]}"
        inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=512)
        with torch.no_grad():
            outputs = model.generate(**inputs, max_new_tokens=20)
        decoded = tokenizer.decode(outputs[0], skip_special_tokens=True)

        doc_type = "unknown"
        for dt in DOCUMENT_TYPES:
            if dt in decoded.lower():
                doc_type = dt
                break

        return ClassificationResult(doc_type=doc_type, confidence=0.85, reasoning="Local adapter prediction")
    except Exception as e:  # noqa: BLE001
        logger.warning("Local adapter inference failed: %s", e)
        return None


def _parse_legacy_response(response) -> dict | None:
    """Fallback: parse text JSON from response for backward compatibility."""
    import json
    try:
        for block in response.content:
            if hasattr(block, "text"):
                return json.loads(block.text)
    except (json.JSONDecodeError, AttributeError):
        pass
    return None
