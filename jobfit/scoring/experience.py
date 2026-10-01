import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from jobfit.schemas.llm import JobRequirement, RequirementMatch, ResumeRole

_YEAR_MONTH = re.compile(r"^(\d{4})-(\d{2})$")
_YEAR_ONLY = re.compile(r"^(\d{4})$")


@dataclass(frozen=True)
class ExperienceSummary:
    months: int
    dates_complete: bool

    @property
    def years(self) -> float:
        return self.months / 12


def parse_month(value: str | None, *, end_date: bool = False) -> int | None:
    if value is None:
        return None
    year_month = _YEAR_MONTH.fullmatch(value.strip())
    year_only = _YEAR_ONLY.fullmatch(value.strip())
    try:
        if year_month:
            year, month = int(year_month.group(1)), int(year_month.group(2))
        elif year_only:
            year, month = int(year_only.group(1)), 12 if end_date else 1
        else:
            return None
        if year < 1 or month < 1 or month > 12:
            return None
    except ValueError:
        return None
    return year * 12 + month - 1


def calculate_experience(
    roles: Sequence[ResumeRole],
    *,
    as_of: date | None = None,
) -> ExperienceSummary:
    current_date = as_of or date.today()
    current_month = current_date.year * 12 + current_date.month - 1
    intervals: list[tuple[int, int]] = []
    dates_complete = bool(roles)

    for role in roles:
        start = parse_month(role.start_date)
        end = (
            current_month
            if role.end_date is None
            else parse_month(role.end_date, end_date=True)
        )
        if start is None or end is None or start > current_month or end < start:
            dates_complete = False
            continue
        intervals.append((start, end + 1))

    if not intervals:
        return ExperienceSummary(months=0, dates_complete=False)

    intervals.sort()
    total_months = 0
    active_start, active_end = intervals[0]
    for start, end in intervals[1:]:
        if start <= active_end:
            active_end = max(active_end, end)
        else:
            total_months += active_end - active_start
            active_start, active_end = start, end
    total_months += active_end - active_start
    return ExperienceSummary(months=total_months, dates_complete=dates_complete)


def enforce_min_years(
    requirements: Sequence[JobRequirement],
    matches: Mapping[str, RequirementMatch],
    experience: ExperienceSummary,
) -> dict[str, RequirementMatch]:
    updated = dict(matches)
    if not experience.dates_complete:
        return updated

    for requirement in requirements:
        if requirement.min_years is None:
            continue
        if experience.months >= requirement.min_years * 12:
            continue
        match = updated[requirement.id]
        updated[requirement.id] = match.model_copy(
            update={
                "verdict": "not_met",
                "reason": (
                    f"The resume documents {experience.years:g} years of total "
                    f"experience; {requirement.min_years} years are required."
                ),
            }
        )
    return updated
