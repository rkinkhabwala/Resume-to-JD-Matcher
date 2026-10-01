import pytest

from jobfit.config import Settings
from jobfit.schemas.llm import JobRequirement, RequirementMatch
from jobfit.scoring.score import calculate_keyword_coverage, calculate_score


def requirement(
    requirement_id: str,
    *,
    importance: str = "must_have",
    category: str = "skill",
    text: str = "SQL",
) -> JobRequirement:
    return JobRequirement(
        id=requirement_id,
        text=text,
        category=category,
        importance=importance,
        min_years=None,
        importance_inferred=False,
    )


def match(requirement_id: str, verdict: str) -> RequirementMatch:
    return RequirementMatch(
        requirement_id=requirement_id,
        verdict=verdict,
        evidence=["SQL"],
        evidence_type="explicit",
        reason="The resume explicitly lists SQL.",
    )


@pytest.mark.parametrize(
    ("verdicts", "expected"),
    [
        (["met"], 100),
        (["partial"], 50),
        (["unclear"], 25),
        (["not_met"], 0),
        (["met", "partial", "not_met"], 64),
    ],
)
def test_weighted_score_points_and_must_have_weights(
    verdicts: list[str],
    expected: int,
) -> None:
    requirements = [requirement(f"r{index}") for index in range(len(verdicts))]
    matches = {
        item.id: match(item.id, verdict)
        for item, verdict in zip(requirements, verdicts, strict=True)
    }
    if len(requirements) == 3:
        requirements[-1] = requirement("r2", importance="nice_to_have")

    outcome = calculate_score(requirements, matches, Settings())

    assert outcome.score == expected
    assert not outcome.capped


def test_knockout_cap_only_applies_to_required_gate_categories() -> None:
    requirements = [
        requirement("r1", text="SQL"),
        requirement("r2", text="Python"),
        requirement("r3", category="experience", text="Five years experience"),
        requirement("r4", importance="nice_to_have", text="Tableau"),
    ]
    matches = {
        "r1": match("r1", "met"),
        "r2": match("r2", "met"),
        "r3": match("r3", "not_met"),
        "r4": match("r4", "met"),
    }

    outcome = calculate_score(requirements, matches, Settings())

    assert outcome.uncapped_score == 70
    assert outcome.score == 65
    assert outcome.capped


def test_nice_to_have_experience_does_not_trigger_knockout_cap() -> None:
    requirements = [
        requirement("r1"),
        requirement(
            "r2",
            importance="nice_to_have",
            category="certification",
            text="Certification",
        ),
    ]
    matches = {"r1": match("r1", "met"), "r2": match("r2", "not_met")}

    outcome = calculate_score(requirements, matches, Settings())

    assert outcome.score == 75
    assert not outcome.capped


def test_empty_requirements_score_zero() -> None:
    assert calculate_score([], {}, Settings()).score == 0


def test_keyword_coverage_is_deterministic_and_ignores_generic_words() -> None:
    requirements = [
        requirement("r1", text="Strong proficiency in Python and SQL"),
        requirement("r2", text="Python"),
        requirement("r3", text="Cloud platform experience"),
    ]

    result = calculate_keyword_coverage(requirements, "Python and SQL are used daily.")

    assert result.percentage == pytest.approx(50)
    assert result.found == ("python", "sql")
    assert result.missing == ("cloud", "platform")


def test_keyword_coverage_is_zero_when_no_skill_keywords_exist() -> None:
    result = calculate_keyword_coverage(
        [requirement("r1", category="education", text="Bachelor degree")],
        "Bachelor degree",
    )

    assert result.percentage == 0
    assert result.found == ()
    assert result.missing == ()
