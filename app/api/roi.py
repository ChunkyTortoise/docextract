"""ROI attribution and report generation endpoints."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.middleware import require_roles
from app.dependencies import get_db
from app.models.api_key import APIKey
from app.models.executive_report import ExecutiveReport
from app.models.job import ExtractionJob
from app.models.record import ExtractedRecord
from app.schemas.responses import (
    ReportGenerateResponse,
    ReportGetResponse,
    ReportListResponse,
    ReportMetadata,
)

router = APIRouter(tags=["roi"])

ARTIFACTS_DIR = Path("storage/reports")
INDEX_PATH = ARTIFACTS_DIR / "index.json"


class ReportGenerateRequest(BaseModel):
    date_from: datetime | None = None
    date_to: datetime | None = None
    format: str = Field(default="both", pattern="^(json|html|both)$")


def _ensure_artifact_dir() -> None:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


def _load_index() -> dict:
    if not INDEX_PATH.exists():
        return {}
    try:
        return json.loads(INDEX_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def _save_index(payload: dict) -> None:
    INDEX_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True))


def _range(date_from: datetime | None, date_to: datetime | None) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    end = date_to or now
    start = date_from or (end - timedelta(days=30))
    return start, end


async def _summary(db: AsyncSession, start: datetime, end: datetime) -> dict:
    jobs_total = (
        await db.execute(
            select(func.count(ExtractionJob.id)).where(
                ExtractionJob.created_at >= start,
                ExtractionJob.created_at <= end,
            )
        )
    ).scalar_one()

    jobs_completed = (
        await db.execute(
            select(func.count(ExtractionJob.id)).where(
                ExtractionJob.created_at >= start,
                ExtractionJob.created_at <= end,
                ExtractionJob.status == "completed",
            )
        )
    ).scalar_one()

    records_total = (
        await db.execute(
            select(func.count(ExtractedRecord.id)).where(
                ExtractedRecord.created_at >= start,
                ExtractedRecord.created_at <= end,
            )
        )
    ).scalar_one()

    records_reviewed = (
        await db.execute(
            select(func.count(ExtractedRecord.id)).where(
                ExtractedRecord.reviewed_at.is_not(None),
                ExtractedRecord.created_at >= start,
                ExtractedRecord.created_at <= end,
            )
        )
    ).scalar_one()

    avg_confidence = (
        await db.execute(
            select(func.avg(ExtractedRecord.confidence_score)).where(
                ExtractedRecord.created_at >= start,
                ExtractedRecord.created_at <= end,
            )
        )
    ).scalar()

    avg_processing_ms = (
        await db.execute(
            select(
                func.avg(
                    func.extract('epoch', ExtractionJob.completed_at - ExtractionJob.started_at) * 1000
                )
            ).where(
                ExtractionJob.created_at >= start,
                ExtractionJob.created_at <= end,
                ExtractionJob.status == "completed",
                ExtractionJob.completed_at.is_not(None),
            )
        )
    ).scalar()

    minutes_saved = float(jobs_completed) * 8.0
    dollars_saved = minutes_saved / 60.0 * 35.0
    estimated_run_cost = float(jobs_total) * 0.12

    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "kpis": {
            "jobs_total": int(jobs_total),
            "jobs_completed": int(jobs_completed),
            "records_total": int(records_total),
            "records_reviewed": int(records_reviewed),
            "avg_confidence": round(float(avg_confidence or 0.0), 4),
            "avg_processing_indicator": round(float(avg_processing_ms or 0.0), 2),
            "estimated_minutes_saved": round(minutes_saved, 2),
            "estimated_dollars_saved": round(dollars_saved, 2),
            "estimated_run_cost": round(estimated_run_cost, 2),
            "net_value": round(dollars_saved - estimated_run_cost, 2),
        },
    }


def _db_metadata(report: ExecutiveReport) -> dict:
    return {
        "report_id": str(report.id),
        "generated_at": report.generated_at.isoformat() if report.generated_at else None,
        "files": list(report.files_json or []),
        "from": report.date_from.isoformat() if report.date_from else None,
        "to": report.date_to.isoformat() if report.date_to else None,
        "format": report.format,
        "status": report.status,
        "error_message": report.error_message,
    }


def _index_metadata(report_id: str, metadata: dict) -> dict:
    return {
        "report_id": report_id,
        "generated_at": metadata.get("generated_at"),
        "files": list(metadata.get("files", [])),
        "from": metadata.get("from"),
        "to": metadata.get("to"),
        "format": metadata.get("format"),
        "status": metadata.get("status"),
        "error_message": metadata.get("error_message"),
    }


@router.get("/roi/summary")
async def roi_summary(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_roles("viewer")),
) -> dict:
    start, end = _range(date_from, date_to)
    return await _summary(db, start, end)


@router.get("/roi/trends")
async def roi_trends(
    interval: str = Query(default="week", pattern="^(week|month)$"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_roles("viewer")),
) -> dict:
    start, end = _range(date_from, date_to)
    step_days = 7 if interval == "week" else 30

    points = []
    cursor = start
    while cursor < end:
        bucket_end = min(cursor + timedelta(days=step_days), end)
        summary = await _summary(db, cursor, bucket_end)
        points.append(
            {
                "bucket_start": cursor.isoformat(),
                "bucket_end": bucket_end.isoformat(),
                "jobs_completed": summary["kpis"]["jobs_completed"],
                "dollars_saved": summary["kpis"]["estimated_dollars_saved"],
                "net_value": summary["kpis"]["net_value"],
            }
        )
        cursor = bucket_end

    return {
        "interval": interval,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "points": points,
    }


@router.post("/reports/generate", response_model=ReportGenerateResponse)
async def generate_report(
    payload: ReportGenerateRequest,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_roles("operator")),
) -> dict:
    _ensure_artifact_dir()
    start, end = _range(payload.date_from, payload.date_to)
    summary = await _summary(db, start, end)

    report_id = str(uuid.uuid4())
    files: list[str] = []

    try:
        if payload.format in {"json", "both"}:
            json_path = ARTIFACTS_DIR / f"{report_id}.json"
            json_path.write_text(json.dumps(summary, indent=2))
            files.append(str(json_path))

        if payload.format in {"html", "both"}:
            html_path = ARTIFACTS_DIR / f"{report_id}.html"
            html_path.write_text(
                "\n".join(
                    [
                        "<html><head><title>DocExtract Executive Report</title></head><body>",
                        "<h1>DocExtract Executive Report</h1>",
                        f"<p>Generated: {datetime.now(timezone.utc).isoformat()}</p>",
                        f"<pre>{json.dumps(summary, indent=2)}</pre>",
                        "</body></html>",
                    ]
                )
            )
            files.append(str(html_path))
    except OSError as exc:
        db.add(
            ExecutiveReport(
                id=report_id,
                date_from=start,
                date_to=end,
                format=payload.format,
                status="failed",
                files_json=list(files),
                summary_json=summary,
                error_message=str(exc),
            )
        )
        await db.commit()
        raise HTTPException(
            status_code=500,
            detail={
                "report_id": report_id,
                "message": f"Failed to write report artifacts: {exc}",
            },
        )

    index = _load_index()
    index[report_id] = {
        "report_id": report_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "format": payload.format,
        "status": "generated",
        "error_message": None,
    }
    _save_index(index)

    db.add(
        ExecutiveReport(
            id=report_id,
            date_from=start,
            date_to=end,
            format=payload.format,
            status="generated",
            files_json=files,
            summary_json=summary,
            error_message=None,
        )
    )
    await db.commit()

    return {"report_id": report_id, "files": files, "status": "generated"}


@router.get("/reports", response_model=ReportListResponse)
async def list_reports(
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_roles("viewer")),
) -> dict:
    models = (
        (
            await db.execute(
                select(ExecutiveReport).order_by(desc(ExecutiveReport.generated_at)).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    if models:
        items = [_db_metadata(model) for model in models]
        return {"items": items}

    index = _load_index()
    fallback_items = [_index_metadata(report_id, metadata) for report_id, metadata in index.items()]
    fallback_items.sort(key=lambda item: item.get("generated_at") or "", reverse=True)
    return {"items": fallback_items[:limit]}


@router.get("/reports/{report_id}", response_model=ReportGetResponse)
async def get_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_roles("viewer")),
) -> dict:
    metadata: dict | None = None

    model = (
        await db.execute(select(ExecutiveReport).where(ExecutiveReport.id == report_id))
    ).scalar_one_or_none()
    if model is not None:
        metadata = _db_metadata(model)

    if metadata is None:
        index = _load_index()
        legacy = index.get(report_id)
        if legacy is None:
            raise HTTPException(status_code=404, detail="Report not found")
        metadata = _index_metadata(report_id, legacy)

    artifacts = []
    for file_path in metadata.get("files", []):
        path = Path(file_path)
        if path.exists():
            artifacts.append(
                {
                    "path": file_path,
                    "content_type": "application/json" if path.suffix == ".json" else "text/html",
                    "content": path.read_text(),
                }
            )

    parsed_metadata = ReportMetadata.model_validate(metadata)
    return {"metadata": parsed_metadata, "artifacts": artifacts}
