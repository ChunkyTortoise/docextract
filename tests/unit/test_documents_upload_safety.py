"""Upload filename + size-bound safety helpers."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.documents import _safe_filename


def test_safe_filename_basenames():
    assert _safe_filename("invoice.pdf") == "invoice.pdf"
    assert _safe_filename("subdir/invoice.pdf") == "invoice.pdf"
    assert _safe_filename(None) == "unknown"
    assert _safe_filename("") == "unknown"


def test_safe_filename_rejects_dot_names():
    with pytest.raises(HTTPException):
        _safe_filename(".")
    with pytest.raises(HTTPException):
        _safe_filename("..")


def test_safe_filename_strips_parent_segments():
    assert _safe_filename("../etc/passwd") == "passwd"
