from typing import Literal

from pydantic import BaseModel, ConfigDict

RequirementCategory = Literal[
    "skill",
    "experience",
    "education",
    "certification",
    "domain",
    "soft_skill",
    "other",
]
Importance = Literal["must_have", "nice_to_have"]
Verdict = Literal["met", "partial", "not_met", "unclear"]
EvidenceType = Literal["explicit", "inferred"]


class StrictOutputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JobRequirement(StrictOutputModel):
    id: str
    text: str
    category: RequirementCategory
    importance: Importance
    min_years: int | None
    importance_inferred: bool


class JobAnalysis(StrictOutputModel):
    role_title: str
    seniority: str
    requirements: list[JobRequirement]


class ResumeRole(StrictOutputModel):
    title: str
    employer: str | None
    start_date: str | None
    end_date: str | None


class EducationEntry(StrictOutputModel):
    degree: str
    institution: str | None
    field: str | None
    completion_date: str | None


class ResumeAnalysis(StrictOutputModel):
    skills: list[str]
    roles: list[ResumeRole]
    education: list[EducationEntry]
    certifications: list[str]


class RequirementMatch(StrictOutputModel):
    requirement_id: str
    verdict: Verdict
    evidence: list[str]
    evidence_type: EvidenceType
    reason: str


class MatchingResult(StrictOutputModel):
    matches: list[RequirementMatch]
