"""Regenerate the three explicitly synthetic comparison HTML documents."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from frontend.comparison_samples import DATA_DIR, render_comparison

if __name__ == "__main__":
    destination = DATA_DIR / "comparison"
    destination.mkdir(exist_ok=True)
    for sample in ("invoice", "contract", "receipt"):
        (destination / f"{sample}.html").write_text(render_comparison(sample), encoding="utf-8")
