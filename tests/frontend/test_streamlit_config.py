"""Checks for the committed Streamlit config used by the demo UI."""
from __future__ import annotations

import tomllib
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[2] / ".streamlit" / "config.toml"


def _load() -> dict:
    with CONFIG_PATH.open("rb") as fh:
        return tomllib.load(fh)


def test_auto_page_nav_is_hidden() -> None:
    # frontend/app.py drives navigation with its own radio; the auto-built
    # pages/ list would duplicate it and expose pages DEMO_MODE hides.
    assert _load()["client"]["showSidebarNavigation"] is False


def test_theme_is_unchanged() -> None:
    theme = _load()["theme"]
    assert theme == {
        "base": "dark",
        "primaryColor": "#06B6D4",
        "backgroundColor": "#0A1215",
        "secondaryBackgroundColor": "#0D1A1F",
        "textColor": "#E2E8F0",
        "font": "sans serif",
    }
