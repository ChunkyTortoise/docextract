from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

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


class GuardrailPiiMatch(BaseModel):
    type: str
    field: str
    redacted: str


class GuardrailSummary(BaseModel):
    passed: bool
    pii_detected: list[GuardrailPiiMatch] = Field(default_factory=list)
    grounding_issues: int = 0


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
    pii_detected: bool = False
    guardrails: GuardrailSummary | None = None
    created_at: datetime


def record_item_from_db(r: Any) -> RecordItem:
    """Build a RecordItem from a DB ExtractedRecord, extracting guardrail metadata."""
    guardrails_data = (r.extracted_data or {}).get("_guardrails")
    guardrails = None
    pii_detected = False
    if guardrails_data:
        pii_list = guardrails_data.get("pii_detected", [])
        grounding = guardrails_data.get("grounding", [])
        ungrounded = sum(1 for g in grounding if g.get("status") == "ungrounded")
        pii_detected = len(pii_list) > 0
        guardrails = GuardrailSummary(
            passed=guardrails_data.get("passed", True),
            pii_detected=[
                GuardrailPiiMatch(type=m["type"], field=m["field"], redacted=m["redacted"])
                for m in pii_list
            ],
            grounding_issues=ungrounded,
        )

    return RecordItem(
        id=str(r.id),
        job_id=str(r.job_id),
        document_id=str(r.document_id),
        document_type=r.document_type,
        extracted_data=r.extracted_data,
        confidence_score=r.confidence_score,
        needs_review=r.needs_review,
        validation_status=r.validation_status,
        review_status=None,
        pii_detected=pii_detected,
        guardrails=guardrails,
        created_at=r.created_at,
    )


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


class ModelStats(BaseModel):
    model: str
    call_count: int
    avg_latency_ms: int
    p95_latency_ms: int
    input_tokens: int
    output_tokens: int
    error_rate: float
    avg_confidence: float
    estimated_cost_usd: float


class OperationStats(BaseModel):
    operation: str
    call_count: int
    avg_latency_ms: int
    error_rate: float


class LLMMetricsResponse(BaseModel):
    hours: int
    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    by_model: list[ModelStats]
    by_operation: list[OperationStats]


class BusinessMetricsResponse(BaseModel):
    straight_through_rate: float
    avg_cost_usd: float
    p50_ms: float
    p95_ms: float
    docs_30d: int
    hitl_escalation_rate: float
