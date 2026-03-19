"""Demo page endpoint — serves static HTML for portfolio visitors."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(tags=["demo"])
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@router.get("/demo", include_in_schema=False)
async def demo_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "demo.html", media_type="text/html")
