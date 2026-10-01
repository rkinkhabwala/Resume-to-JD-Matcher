from typing import Literal

from pydantic import BaseModel, ConfigDict

from jobfit.schemas.llm import (
    EvidenceType,
    Importance,
    RequirementCategory,
    Verdict,
)


class ReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Confidence(ReportModel):
    value: float
    label: Literal["High", "Medium", "Low"]
    reasons: list[str]


class ReportRequirement(ReportModel):
    id: str
    text: str
    category: RequirementCategory
    importance: Importance
    importance_inferred: bool
    min_years: int | None
    verdict: Verdict
    evidence: list[str]
    evidence_type: EvidenceType
    reason: str


class ReportTokenUsage(ReportModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: float | None


class AnalysisReport(ReportModel):
    score: int
    confidence: Confidence
    summary: str
    requirements: list[ReportRequirement]
    strengths: list[str]
    gaps: list[str]
    resume_suggestions: list[str]
    keyword_coverage: float
    model: str
    prompt_version: str
    usage: ReportTokenUsage
    timings_ms: dict[str, int]
    warnings: list[str]
