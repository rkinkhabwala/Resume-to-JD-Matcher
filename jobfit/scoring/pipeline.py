from __future__ import annotations

import json
import random
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from jobfit.cache.key import result_cache_key
from jobfit.cache.protocol import ResultCache
from jobfit.config import Settings
from jobfit.extraction.job import JobSource
from jobfit.extraction.pii import redact_pii
from jobfit.llm.prompts import (
    PROMPT_VERSION,
    load_system_prompt,
    render_job_analysis_user,
    render_matching_user,
    render_resume_analysis_user,
)
from jobfit.llm.protocol import LLMClient, TokenUsage
from jobfit.schemas.llm import (
    JobAnalysis,
    JobRequirement,
    MatchingResult,
    RequirementMatch,
    ResumeAnalysis,
)
from jobfit.schemas.report import (
    AnalysisReport,
    ReportRequirement,
    ReportTokenUsage,
)
from jobfit.scoring.confidence import (
    calculate_confidence,
    calculate_resume_parse_quality,
)
from jobfit.scoring.evidence import EvidenceVerification, verify_evidence
from jobfit.scoring.experience import calculate_experience, enforce_min_years
from jobfit.scoring.score import calculate_keyword_coverage, calculate_score

_NORMALIZE_REQUIREMENT = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class _MatchingRun:
    matches: dict[str, RequirementMatch]
    score: int
    verification: EvidenceVerification


@dataclass(frozen=True)
class AnalysisOutcome:
    report: AnalysisReport
    run_scores: tuple[int, ...]


class AnalysisPipeline:
    def __init__(
        self,
        llm_client: LLMClient,
        settings: Settings,
        *,
        model: str,
        prompt_version: str = PROMPT_VERSION,
        cache: ResultCache | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._settings = settings
        self._model = model
        self._prompt_version = prompt_version
        self._cache = cache

    def analyze(
        self,
        resume_text: str,
        job_text: str,
        job_source: JobSource,
    ) -> AnalysisReport:
        return self.analyze_with_diagnostics(
            resume_text,
            job_text,
            job_source,
        ).report

    def analyze_with_diagnostics(
        self,
        resume_text: str,
        job_text: str,
        job_source: JobSource,
    ) -> AnalysisOutcome:
        cache_key = result_cache_key(
            resume_text,
            job_text,
            self._model,
            self._prompt_version,
            job_source,
        )
        if self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return AnalysisOutcome(report=cached, run_scores=())

        total_started = time.perf_counter()
        safe_resume = redact_pii(resume_text)
        safe_job = redact_pii(job_text)
        timings: dict[str, int] = {}
        usages: list[TokenUsage] = []

        step_started = time.perf_counter()
        job_analysis, usage = self._llm_client.parse(
            load_system_prompt("job_analysis", self._prompt_version),
            render_job_analysis_user(safe_job),
            JobAnalysis,
        )
        usages.append(usage)
        job_analysis = _validate_job_analysis(job_analysis)
        timings["job_analysis"] = _elapsed_ms(step_started)

        step_started = time.perf_counter()
        resume_analysis, usage = self._llm_client.parse(
            load_system_prompt("resume_analysis", self._prompt_version),
            render_resume_analysis_user(safe_resume),
            ResumeAnalysis,
        )
        usages.append(usage)
        experience = calculate_experience(resume_analysis.roles)
        timings["resume_analysis"] = _elapsed_ms(step_started)

        step_started = time.perf_counter()
        runs: list[_MatchingRun] = []
        for run_number in range(3):
            ordered_requirements = _shuffled_requirements(
                job_analysis.requirements,
                run_number,
            )
            requirements_json = json.dumps(
                [item.model_dump(mode="json") for item in ordered_requirements],
                ensure_ascii=True,
                separators=(",", ":"),
            )
            matching_result, usage = self._llm_client.parse(
                load_system_prompt("matching", self._prompt_version),
                render_matching_user(safe_job, safe_resume, requirements_json),
                MatchingResult,
            )
            usages.append(usage)
            matches = _validate_matching_result(
                matching_result,
                job_analysis.requirements,
            )
            matches = enforce_min_years(job_analysis.requirements, matches, experience)
            verification = verify_evidence(matches, safe_resume)
            score = calculate_score(
                job_analysis.requirements,
                verification.matches,
                self._settings,
            )
            runs.append(
                _MatchingRun(
                    matches=verification.matches,
                    score=score.score,
                    verification=verification,
                )
            )
        timings["matching"] = _elapsed_ms(step_started)

        representative = sorted(runs, key=lambda run: run.score)[1]
        run_scores = [run.score for run in runs]
        verification = EvidenceVerification(
            matches=representative.matches,
            submitted_quotes=sum(run.verification.submitted_quotes for run in runs),
            verified_quotes=sum(run.verification.verified_quotes for run in runs),
            downgrades=sum(run.verification.downgrades for run in runs),
        )
        parse_quality = calculate_resume_parse_quality(safe_resume, resume_analysis)
        confidence = calculate_confidence(
            list(representative.matches.values()),
            run_scores,
            requirement_count=len(job_analysis.requirements),
            resume_parse_quality=parse_quality,
            job_source=job_source,
            submitted_quotes=verification.submitted_quotes,
            verified_quotes=verification.verified_quotes,
            settings=self._settings,
        )
        keyword_coverage = calculate_keyword_coverage(
            job_analysis.requirements,
            safe_resume,
        )
        report_requirements = _report_requirements(
            job_analysis.requirements,
            representative.matches,
        )
        summary = _build_summary(representative.score, report_requirements)
        strengths = [item.text for item in report_requirements if item.verdict == "met"]
        gaps = [
            item.text
            for item in sorted(report_requirements, key=_gap_sort_key)
            if item.verdict != "met"
        ]
        suggestions = _build_suggestions(report_requirements)
        warnings: list[str] = []
        if verification.downgrades:
            warnings.append(
                f"Evidence verification downgraded {verification.downgrades} "
                "verdicts to unclear across the matching runs."
            )
        if not experience.dates_complete and any(
            requirement.min_years is not None
            for requirement in job_analysis.requirements
        ):
            warnings.append(
                "Role dates were incomplete; numeric experience requirements "
                "could not be fully verified."
            )
        if not keyword_coverage.found and not keyword_coverage.missing:
            warnings.append(
                "No hard-skill keywords were available for coverage analysis."
            )

        combined_usage = _sum_usage(usages)
        estimated_cost = (
            combined_usage.input_tokens
            * self._settings.llm_input_price_per_million_tokens
            + combined_usage.output_tokens
            * self._settings.llm_output_price_per_million_tokens
        ) / 1_000_000
        timings["scoring"] = max(
            0,
            _elapsed_ms(total_started)
            - sum(
                timings.get(key, 0)
                for key in ("job_analysis", "resume_analysis", "matching")
            ),
        )
        timings["total"] = _elapsed_ms(total_started)
        report = AnalysisReport(
            score=representative.score,
            confidence=confidence,
            summary=summary,
            requirements=report_requirements,
            strengths=strengths,
            gaps=gaps,
            resume_suggestions=suggestions,
            keyword_coverage=keyword_coverage.percentage,
            model=self._model,
            prompt_version=self._prompt_version,
            usage=ReportTokenUsage(
                input_tokens=combined_usage.input_tokens,
                output_tokens=combined_usage.output_tokens,
                total_tokens=combined_usage.total_tokens,
                estimated_cost_usd=round(estimated_cost, 8),
            ),
            timings_ms=timings,
            warnings=warnings,
        )
        if self._cache is not None:
            self._cache.set(cache_key, report)
        return AnalysisOutcome(report=report, run_scores=tuple(run_scores))


def _validate_job_analysis(analysis: JobAnalysis) -> JobAnalysis:
    if len(analysis.requirements) > 25:
        raise ValueError("Job analysis returned more than 25 requirements.")
    normalized: set[str] = set()
    ids: set[str] = set()
    requirements: list[JobRequirement] = []
    for requirement in analysis.requirements:
        normalized_text = _NORMALIZE_REQUIREMENT.sub(
            " ", requirement.text.casefold()
        ).strip()
        if not normalized_text:
            raise ValueError("Job analysis returned an empty requirement.")
        if normalized_text in normalized:
            continue
        if requirement.id in ids:
            raise ValueError("Job analysis returned duplicate requirement IDs.")
        normalized.add(normalized_text)
        ids.add(requirement.id)
        requirements.append(requirement)
    return analysis.model_copy(update={"requirements": requirements})


def _validate_matching_result(
    result: MatchingResult,
    requirements: Sequence[JobRequirement],
) -> dict[str, RequirementMatch]:
    expected_ids = {requirement.id for requirement in requirements}
    matches: dict[str, RequirementMatch] = {}
    for match in result.matches:
        if match.requirement_id not in expected_ids:
            raise ValueError("Matching result contains an unknown requirement ID.")
        if match.requirement_id in matches:
            raise ValueError("Matching result contains duplicate requirement IDs.")
        matches[match.requirement_id] = match
    if matches.keys() != expected_ids:
        raise ValueError(
            "Matching result must include exactly one match per requirement."
        )
    return matches


def _shuffled_requirements(
    requirements: Sequence[JobRequirement],
    run_number: int,
) -> list[JobRequirement]:
    ordered = list(requirements)
    if len(ordered) < 2:
        return ordered
    random.Random(run_number + len(ordered)).shuffle(ordered)
    if [item.id for item in ordered] == [item.id for item in requirements]:
        offset = (run_number % (len(ordered) - 1)) + 1
        ordered = ordered[offset:] + ordered[:offset]
    return ordered


def _report_requirements(
    requirements: Sequence[JobRequirement],
    matches: Mapping[str, RequirementMatch],
) -> list[ReportRequirement]:
    return [
        ReportRequirement(
            id=requirement.id,
            text=requirement.text,
            category=requirement.category,
            importance=requirement.importance,
            importance_inferred=requirement.importance_inferred,
            min_years=requirement.min_years,
            verdict=matches[requirement.id].verdict,
            evidence=matches[requirement.id].evidence,
            evidence_type=matches[requirement.id].evidence_type,
            reason=matches[requirement.id].reason,
        )
        for requirement in requirements
    ]


def _gap_sort_key(requirement: ReportRequirement) -> tuple[int, int, str]:
    importance = 0 if requirement.importance == "must_have" else 1
    verdict = {"not_met": 0, "partial": 1, "unclear": 2, "met": 3}[requirement.verdict]
    return importance, verdict, requirement.text.casefold()


def _build_summary(score: int, requirements: Sequence[ReportRequirement]) -> str:
    if not requirements:
        return (
            "No distinct job requirements were available to score; "
            "the match score is 0/100."
        )
    evidence_backed = sum(item.verdict in {"met", "partial"} for item in requirements)
    return (
        f"Evidence supports {evidence_backed} of {len(requirements)} listed "
        "requirements; "
        f"the deterministic match score is {score}/100."
    )


def _build_suggestions(requirements: Sequence[ReportRequirement]) -> list[str]:
    return [
        f"Consider foregrounding this existing evidence for {item.text}: "
        f"{item.evidence[0]}"
        for item in requirements
        if item.verdict in {"met", "partial"} and item.evidence
    ]


def _sum_usage(usages: Sequence[TokenUsage]) -> TokenUsage:
    return TokenUsage(
        input_tokens=sum(item.input_tokens for item in usages),
        output_tokens=sum(item.output_tokens for item in usages),
    )


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
