from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class AnalysisRecord:
    analysis_id: str
    status: str = "queued"
    progress: str = "queued"
    message: str = "Queued for analysis."
    result: dict[str, Any] | None = None
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    job_url: str | None = None
    job_text: str | None = None
    resume_text: str | None = None


class AnalysisStore:
    def __init__(self) -> None:
        self._jobs: dict[str, AnalysisRecord] = {}

    def create(
        self,
        *,
        job_url: str | None = None,
        job_text: str | None = None,
        resume_text: str | None = None,
    ) -> AnalysisRecord:
        record = AnalysisRecord(
            analysis_id=str(uuid4()),
            status="queued",
            progress="queued",
            message="Queued for analysis.",
            job_url=job_url,
            job_text=job_text,
            resume_text=resume_text,
        )
        self._jobs[record.analysis_id] = record
        return record

    def get(self, analysis_id: str) -> AnalysisRecord | None:
        return self._jobs.get(analysis_id)

    def update(
        self,
        analysis_id: str,
        *,
        status: str | None = None,
        progress: str | None = None,
        message: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> AnalysisRecord | None:
        record = self._jobs.get(analysis_id)
        if record is None:
            return None
        if status is not None:
            record.status = status
        if progress is not None:
            record.progress = progress
        if message is not None:
            record.message = message
        if result is not None:
            record.result = result
        record.updated_at = _utc_now()
        return record


analysis_store = AnalysisStore()
