from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.events import JobStatus


class JobResponse(BaseModel):
    id: str
    document_id: str
    status: JobStatus
    progress: int
    priority: str
    stage_detail: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    processing_time_ms: int | None = None


class UploadResponse(BaseModel):
    document_id: str
    job_id: str
    filename: str
    duplicate: bool = False
    message: str


class UploadBatchResponse(BaseModel):
    jobs: list[UploadResponse]


class RecordItem(BaseModel):
    id: str
    job_id: str
    document_id: str
    document_type: str
    extracted_data: dict
    confidence_score: float
    needs_review: bool
    validation_status: str | None = None
    review_status: str | None = None
    created_at: datetime


class PaginatedRecords(BaseModel):
    items: list[RecordItem]
    total: int
    page: int
    page_size: int
    has_next: bool


class StatsResponse(BaseModel):
    total_documents: int
    total_jobs: int
    completed_jobs: int
    failed_jobs: int
    needs_review: int
    success_rate: float
    avg_processing_time_ms: float | None
    avg_confidence_score: float | None
    doc_type_breakdown: dict[str, int]
    jobs_last_24h: int


class HealthResponse(BaseModel):
    status: Literal["healthy", "degraded"]
    db_ok: bool
    redis_ok: bool
    storage_ok: bool = True
    version: str = "1.0.0"


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
    request_id: str | None = None


class ReportArtifact(BaseModel):
    path: str
    content_type: str
    content: str


class ReportMetadata(BaseModel):
    report_id: str
    generated_at: datetime | None = None
    from_: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None
    format: str | None = None
    status: str | None = None
    error_message: str | None = None
    files: list[str] = Field(default_factory=list)


class ReportGenerateResponse(BaseModel):
    report_id: str
    files: list[str]
    status: str


class ReportGetResponse(BaseModel):
    metadata: ReportMetadata
    artifacts: list[ReportArtifact]


class ReportListResponse(BaseModel):
    items: list[ReportMetadata]


class KPIs(BaseModel):
    jobs_total: int
    jobs_completed: int
    records_total: int
    records_reviewed: int
    avg_confidence: float
    avg_processing_indicator: float
    estimated_minutes_saved: float
    estimated_dollars_saved: float
    estimated_run_cost: float
    net_value: float


class ROISummaryResponse(BaseModel):
    from_: str = Field(alias="from")
    to: str
    kpis: KPIs


class TrendPoint(BaseModel):
    bucket_start: str
    bucket_end: str
    jobs_completed: int
    dollars_saved: float
    net_value: float


class ROITrendsResponse(BaseModel):
    interval: str
    from_: str = Field(alias="from")
    to: str
    points: list[TrendPoint]
