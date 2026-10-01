import re
from collections.abc import Mapping
from dataclasses import dataclass

from rapidfuzz.fuzz import partial_ratio

from jobfit.schemas.llm import RequirementMatch

MIN_EVIDENCE_MATCH_RATIO = 90
MAX_EVIDENCE_WORDS = 25


@dataclass(frozen=True)
class EvidenceVerification:
    matches: dict[str, RequirementMatch]
    submitted_quotes: int
    verified_quotes: int
    downgrades: int


def verify_evidence(
    matches: Mapping[str, RequirementMatch],
    resume_text: str,
) -> EvidenceVerification:
    normalized_resume = _normalize(resume_text)
    verified_matches: dict[str, RequirementMatch] = {}
    submitted_quotes = 0
    verified_quotes = 0
    downgrades = 0

    for requirement_id, match in matches.items():
        verified_evidence: list[str] = []
        for quote in match.evidence:
            submitted_quotes += 1
            normalized_quote = _normalize(quote)
            if not normalized_quote or len(quote.split()) > MAX_EVIDENCE_WORDS:
                continue
            if (
                partial_ratio(normalized_quote, normalized_resume)
                >= MIN_EVIDENCE_MATCH_RATIO
            ):
                verified_evidence.append(quote)
                verified_quotes += 1

        updated = match.model_copy(update={"evidence": verified_evidence})
        if match.verdict in {"met", "partial"} and not verified_evidence:
            updated = updated.model_copy(
                update={
                    "verdict": "unclear",
                    "reason": (
                        f"{match.reason} No evidence quote could be verified against "
                        "the resume, so the verdict was downgraded to unclear."
                    ),
                }
            )
            downgrades += 1
        verified_matches[requirement_id] = updated

    return EvidenceVerification(
        matches=verified_matches,
        submitted_quotes=submitted_quotes,
        verified_quotes=verified_quotes,
        downgrades=downgrades,
    )


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()
