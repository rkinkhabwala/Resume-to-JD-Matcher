from datetime import date

from jobfit.schemas.llm import JobRequirement, RequirementMatch, ResumeRole
from jobfit.scoring.experience import (
    ExperienceSummary,
    calculate_experience,
    enforce_min_years,
)


def role(start: str | None, end: str | None) -> ResumeRole:
    return ResumeRole(
        title="Engineer",
        employer=None,
        start_date=start,
        end_date=end,
    )


def test_union_of_overlapping_roles_avoids_double_counting() -> None:
    result = calculate_experience(
        [role("2020-01", "2021-12"), role("2021-01", "2022-12")],
        as_of=date(2024, 1, 1),
    )

    assert result.months == 36
    assert result.years == 3
    assert result.dates_complete


def test_open_role_end_date_extends_through_current_month() -> None:
    result = calculate_experience([role("2023-01", None)], as_of=date(2024, 3, 1))

    assert result.months == 15
    assert result.dates_complete


def test_invalid_or_missing_role_start_date_makes_total_incomplete() -> None:
    result = calculate_experience(
        [role("2020-01", "2020-12"), role(None, None)],
        as_of=date(2024, 1, 1),
    )

    assert result.months == 12
    assert not result.dates_complete


def test_year_only_dates_cover_full_calendar_year() -> None:
    result = calculate_experience([role("2020", "2020")], as_of=date(2024, 1, 1))

    assert result.months == 12
    assert result.dates_complete


def test_min_years_override_requires_complete_dates() -> None:
    requirement = JobRequirement(
        id="exp",
        text="Five years of experience",
        category="experience",
        importance="must_have",
        min_years=5,
        importance_inferred=False,
    )
    match = RequirementMatch(
        requirement_id="exp",
        verdict="partial",
        evidence=["Four years building software"],
        evidence_type="explicit",
        reason="Related experience is documented.",
    )

    incomplete = enforce_min_years(
        [requirement], {"exp": match}, ExperienceSummary(48, False)
    )
    complete = enforce_min_years(
        [requirement], {"exp": match}, ExperienceSummary(48, True)
    )

    assert incomplete["exp"].verdict == "partial"
    assert complete["exp"].verdict == "not_met"
    assert "4 years" in complete["exp"].reason
