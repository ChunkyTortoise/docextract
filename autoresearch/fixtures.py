"""Golden response fixture loader for API-free eval."""
from __future__ import annotations
import json
from pathlib import Path

GOLDEN_DIR = Path(__file__).parent / "golden_responses"


def load_golden_response(case_id: str) -> dict | None:
    """Load a golden response fixture by case ID. Returns None if not found."""
    path = GOLDEN_DIR / f"{case_id}.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def list_golden_cases() -> list[str]:
    """List all available golden case IDs."""
    if not GOLDEN_DIR.exists():
        return []
    return sorted(p.stem for p in GOLDEN_DIR.glob("*.json"))
