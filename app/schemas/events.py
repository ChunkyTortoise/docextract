from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class JobStatus(str, Enum):
    QUEUED = "queued"
    PREPROCESSING = "preprocessing"
    EXTRACTING_TEXT = "extracting_text"
    CLASSIFYING = "classifying"
    EXTRACTING_DATA = "extracting_data"
    VALIDATING = "validating"
    EMBEDDING = "embedding"
    COMPLETED = "completed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"
    CANCELLED = "cancelled"


JOB_STATUS_PROGRESS: dict[str, int] = {
    JobStatus.QUEUED: 0,
    JobStatus.PREPROCESSING: 5,
    JobStatus.EXTRACTING_TEXT: 15,
    JobStatus.CLASSIFYING: 35,
    JobStatus.EXTRACTING_DATA: 40,
    JobStatus.VALIDATING: 75,
    JobStatus.EMBEDDING: 90,
    JobStatus.COMPLETED: 100,
    JobStatus.NEEDS_REVIEW: 100,
    JobStatus.FAILED: -1,
    JobStatus.CANCELLED: -1,
}


@dataclass
class JobEvent:
    job_id: str
    status: JobStatus
    progress: int
    message: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    details: dict = field(default_factory=dict)
