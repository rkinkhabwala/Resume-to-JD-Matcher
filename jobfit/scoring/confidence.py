from collections.abc import Sequence
from typing import Literal

from jobfit.config import Settings
from jobfit.extraction.job import JobSource
from jobfit.schemas.llm import RequirementMatch, ResumeAnalysis
from jobfit.schemas.report import Confidence
from jobfit.scoring.experience import calculate_experience


def calculate_consistency(scores: Sequence[int]) -> float:
    if not scores:
        return 0.0
    spread = max(scores) - min(scores)
    if spread <= 5:
        return 1.0
    if spread >= 20:
        return 0.0
    return (20 - spread) / 15


def calculate_resume_parse_quality(
    resume_text: str,
    analysis: ResumeAnalysis,
) -> float:
    text_quality = float(len(resume_text.strip()) >= 200)
    sections = (bool(analysis.skills), bool(analysis.roles), bool(analysis.education))
    section_quality = sum(sections) / len(sections)
    if analysis.roles:
        dated_roles = sum(
            calculate_experience([role]).dates_complete for role in analysis.roles
        )
        role_date_quality = dated_roles / len(analysis.roles)
    else:
        role_date_quality = 0.0
    return (text_quality + section_quality + role_date_quality) / 3


def calculate_confidence(
    matches: Sequence[RequirementMatch],
    run_scores: Sequence[int],
    *,
    requirement_count: int,
    resume_parse_quality: float,
    job_source: JobSource,
    submitted_quotes: int,
    verified_quotes: int,
    settings: Settings,
) -> Confidence:
    consistency = calculate_consistency(run_scores)
    evidence_strength = _evidence_strength(matches)
    requirement_quality = min(requirement_count / 8, 1.0)
    source_quality = _source_quality(job_source)
    input_quality = (
        settings.confidence_requirement_quality_weight * requirement_quality
        + settings.confidence_resume_quality_weight * resume_parse_quality
        + settings.confidence_source_quality_weight * source_quality
    )
    verification = verified_quotes / submitted_quotes if submitted_quotes > 0 else 0.0
    raw_value = (
        settings.confidence_consistency_weight * consistency
        + settings.confidence_evidence_weight * evidence_strength
        + settings.confidence_input_weight * input_quality
        + settings.confidence_verification_weight * verification
    )
    value = round(min(max(raw_value, 0.0), 1.0), 4)

    reasons: list[str] = []
    if requirement_count <= 3:
        reasons.append(f"The posting listed only {requirement_count} requirements.")
    spread = max(run_scores) - min(run_scores) if run_scores else 0
    if spread > 5:
        reasons.append(f"The three matching runs differed by {spread} points.")
    if resume_parse_quality < 0.5:
        reasons.append("The resume had limited extractable or structured information.")
    if job_source == "generic_scrape":
        reasons.append("The job description came from a generic page extraction.")
    if evidence_strength < 0.5:
        reasons.append("Many requirement judgments were inferred or unclear.")
    if verification < 0.8:
        reasons.append(
            "Some resume evidence could not be verified against the source text."
        )
    if not reasons:
        reasons.append(
            "Inputs, matching runs, and resume evidence were consistently clear."
        )

    label: Literal["High", "Medium", "Low"] = (
        "High" if value >= 0.75 else "Medium" if value >= 0.5 else "Low"
    )
    return Confidence(value=value, label=label, reasons=reasons)


def _evidence_strength(matches: Sequence[RequirementMatch]) -> float:
    if not matches:
        return 0.0
    explicit = sum(
        match.evidence_type == "explicit" and match.verdict != "unclear"
        for match in matches
    )
    return explicit / len(matches)


def _source_quality(source: JobSource) -> float:
    if source in {"pasted", "json_ld", "ats_api"}:
        return 1.0
    if source == "generic_scrape":
        return 0.5
    return 0.0
