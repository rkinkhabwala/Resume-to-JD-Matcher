import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from jobfit.config import Settings
from jobfit.schemas.llm import JobRequirement, RequirementMatch

_TOKEN = re.compile(r"[a-z0-9][a-z0-9+#.]*", re.IGNORECASE)
_STOP_WORDS = {
    "a",
    "ability",
    "an",
    "and",
    "at",
    "experience",
    "for",
    "in",
    "including",
    "knowledge",
    "of",
    "on",
    "or",
    "preferred",
    "proficiency",
    "required",
    "skill",
    "skills",
    "strong",
    "the",
    "to",
    "using",
    "with",
    "year",
    "years",
}


@dataclass(frozen=True)
class ScoreOutcome:
    score: int
    uncapped_score: int
    capped: bool


@dataclass(frozen=True)
class KeywordCoverage:
    percentage: float
    found: tuple[str, ...]
    missing: tuple[str, ...]


def calculate_score(
    requirements: Sequence[JobRequirement],
    matches: Mapping[str, RequirementMatch],
    settings: Settings,
) -> ScoreOutcome:
    if not requirements:
        return ScoreOutcome(score=0, uncapped_score=0, capped=False)

    points = {
        "met": settings.score_met_points,
        "partial": settings.score_partial_points,
        "unclear": settings.score_unclear_points,
        "not_met": settings.score_not_met_points,
    }
    weights = {
        "must_have": settings.score_must_have_weight,
        "nice_to_have": settings.score_nice_to_have_weight,
    }
    denominator = sum(weights[requirement.importance] for requirement in requirements)
    if denominator <= 0:
        raise ValueError("Requirement weights must sum to a positive value.")

    weighted_points = sum(
        weights[requirement.importance] * points[matches[requirement.id].verdict]
        for requirement in requirements
    )
    uncapped_score = round(100 * weighted_points / denominator)
    has_knockout = any(
        requirement.importance == "must_have"
        and requirement.category in {"experience", "education", "certification"}
        and matches[requirement.id].verdict == "not_met"
        for requirement in requirements
    )
    score = (
        min(uncapped_score, settings.score_knockout_cap)
        if has_knockout
        else uncapped_score
    )
    return ScoreOutcome(
        score=score,
        uncapped_score=uncapped_score,
        capped=score != uncapped_score,
    )


def calculate_keyword_coverage(
    requirements: Sequence[JobRequirement],
    resume_text: str,
) -> KeywordCoverage:
    keywords = {
        token.casefold()
        for requirement in requirements
        if requirement.category == "skill"
        for token in _TOKEN.findall(requirement.text)
        if token.casefold() not in _STOP_WORDS and not token.isdigit()
    }
    if not keywords:
        return KeywordCoverage(percentage=0.0, found=(), missing=())

    resume_terms = {token.casefold() for token in _TOKEN.findall(resume_text)}
    found = tuple(sorted(keywords & resume_terms))
    missing = tuple(sorted(keywords - resume_terms))
    percentage = round(100 * len(found) / len(keywords), 2)
    return KeywordCoverage(percentage=percentage, found=found, missing=missing)
