"""Demo mode data loader — serves cached results when DEMO_MODE=true."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DEMO_DATA_DIR = Path(__file__).parent / "demo_data"

_SAMPLES = {
    "invoice": "invoice_sample.json",
    "contract": "contract_sample.json",
    "receipt": "receipt_sample.json",
}


def load_demo_extraction(doc_type: str) -> dict[str, Any]:
    """Return cached extraction result for the given document type."""
    filename = _SAMPLES.get(doc_type)
    if not filename:
        raise ValueError(f"No demo data for doc_type={doc_type!r}")
    return json.loads((_DEMO_DATA_DIR / filename).read_text())


def load_demo_search() -> dict[str, Any]:
    return json.loads((_DEMO_DATA_DIR / "search_sample.json").read_text())


def load_demo_eval() -> dict[str, Any]:
    return json.loads((_DEMO_DATA_DIR / "eval_sample.json").read_text())


def list_demo_doc_types() -> list[str]:
    return list(_SAMPLES.keys())
