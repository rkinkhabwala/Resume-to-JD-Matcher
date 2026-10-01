import pytest

from jobfit.config import Settings
from jobfit.schemas.llm import RequirementMatch
from jobfit.scoring.confidence import calculate_confidence, calculate_consistency


def make_match(
    requirement_id: str,
    verdict: str,
    evidence_type: str = "explicit",
) -> RequirementMatch:
    return RequirementMatch(
        requirement_id=requirement_id,
        verdict=verdict,
        evidence=["SQL"],
        evidence_type=evidence_type,
        reason="Evidence was checked.",
    )


@pytest.mark.parametrize(
    ("scores", "expected"),
    [([80, 84, 85], 1.0), ([70, 77, 78], pytest.approx(12 / 15)), ([10, 50, 90], 0.0)],
)
def test_consistency_uses_spread_thresholds(
    scores: list[int],
    expected: float,
) -> None:
    assert calculate_consistency(scores) == expected


def test_all_unclear_verdicts_have_low_evidence_strength() -> None:
    confidence = calculate_confidence(
        [make_match("r1", "unclear"), make_match("r2", "unclear")],
        [25, 25, 25],
        requirement_count=8,
        resume_parse_quality=1.0,
        job_source="pasted",
        submitted_quotes=0,
        verified_quotes=0,
        settings=Settings(),
    )

    assert confidence.value == pytest.approx(0.3 + 0.25 * 1 + 0.3 * 0 + 0.15 * 0)
    assert confidence.label == "Medium"
    assert any("inferred or unclear" in reason for reason in confidence.reasons)


def test_huge_run_spread_and_few_requirements_reduce_confidence() -> None:
    confidence = calculate_confidence(
        [make_match("r1", "met", "inferred")],
        [20, 50, 90],
        requirement_count=3,
        resume_parse_quality=0.4,
        job_source="generic_scrape",
        submitted_quotes=1,
        verified_quotes=0,
        settings=Settings(),
    )

    assert confidence.value < 0.5
    assert confidence.label == "Low"
    assert any("only 3 requirements" in reason for reason in confidence.reasons)
    assert any("differed by 70 points" in reason for reason in confidence.reasons)
    assert any("generic page" in reason for reason in confidence.reasons)


def test_confidence_is_high_when_signals_are_strong() -> None:
    confidence = calculate_confidence(
        [make_match("r1", "met") for _ in range(8)],
        [90, 92, 94],
        requirement_count=8,
        resume_parse_quality=1.0,
        job_source="json_ld",
        submitted_quotes=8,
        verified_quotes=8,
        settings=Settings(),
    )

    assert confidence.label == "High"
    assert confidence.value >= 0.75
    assert len(confidence.reasons) == 1
