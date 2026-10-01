from jobfit.schemas.llm import RequirementMatch
from jobfit.scoring.evidence import verify_evidence


def requirement_match(
    requirement_id: str,
    verdict: str,
    evidence: list[str],
) -> RequirementMatch:
    return RequirementMatch(
        requirement_id=requirement_id,
        verdict=verdict,
        evidence=evidence,
        evidence_type="explicit",
        reason="The resume supports this requirement.",
    )


def test_verified_quote_is_kept_and_unverified_quote_is_dropped() -> None:
    matches = {
        "r1": requirement_match(
            "r1",
            "met",
            ["Built Python data pipelines", "Managed a large sales organization"],
        )
    }

    result = verify_evidence(matches, "Built Python data pipelines for analytics.")

    assert result.matches["r1"].evidence == ["Built Python data pipelines"]
    assert result.submitted_quotes == 2
    assert result.verified_quotes == 1
    assert result.downgrades == 0


def test_met_without_verified_evidence_is_downgraded() -> None:
    result = verify_evidence(
        {"r1": requirement_match("r1", "met", ["Invented platform experience"])},
        "Resume text lists Python and SQL projects.",
    )

    assert result.matches["r1"].verdict == "unclear"
    assert result.matches["r1"].evidence == []
    assert result.downgrades == 1


def test_partial_without_evidence_is_downgraded_but_not_met_is_not() -> None:
    result = verify_evidence(
        {
            "r1": requirement_match("r1", "partial", []),
            "r2": requirement_match("r2", "not_met", []),
        },
        "Resume text has sufficient length to represent a realistic applicant profile.",
    )

    assert result.matches["r1"].verdict == "unclear"
    assert result.matches["r2"].verdict == "not_met"
    assert result.downgrades == 1


def test_quotes_over_twenty_five_words_are_dropped() -> None:
    quote = "word " * 26
    result = verify_evidence(
        {"r1": requirement_match("r1", "met", [quote])},
        quote,
    )

    assert result.matches["r1"].evidence == []
    assert result.matches["r1"].verdict == "unclear"
    assert result.submitted_quotes == 1
    assert result.verified_quotes == 0
