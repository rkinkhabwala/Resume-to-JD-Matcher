import json
from pathlib import Path

import pytest

from evals.run import load_cases, run_evaluations
from jobfit.config import Settings
from jobfit.llm.fake import FakeLLMClient
from jobfit.llm.protocol import TokenUsage
from jobfit.schemas.llm import (
    EducationEntry,
    JobAnalysis,
    JobRequirement,
    MatchingResult,
    RequirementMatch,
    ResumeAnalysis,
    ResumeRole,
)
from jobfit_cli import cli

FIXTURES = Path(__file__).parents[1] / "fixtures" / "resumes"


def fake_client() -> FakeLLMClient:
    requirement = JobRequirement(
        id="python",
        text="Python",
        category="skill",
        importance="must_have",
        min_years=None,
        importance_inferred=False,
    )
    job = JobAnalysis(
        role_title="Analyst",
        seniority="mid-level",
        requirements=[requirement],
    )
    resume = ResumeAnalysis(
        skills=["Python"],
        roles=[
            ResumeRole(
                title="Analyst",
                employer=None,
                start_date="2020-01",
                end_date=None,
            )
        ],
        education=[
            EducationEntry(
                degree="BSc",
                institution=None,
                field="Statistics",
                completion_date=None,
            )
        ],
        certifications=[],
    )
    matching = MatchingResult(
        matches=[
            RequirementMatch(
                requirement_id="python",
                verdict="met",
                evidence=["Developed Python pipelines and Tableau dashboards"],
                evidence_type="explicit",
                reason="Python work is listed.",
            )
        ]
    )
    responses = [
        (job, TokenUsage(10, 4)),
        (resume, TokenUsage(10, 4)),
        (matching, TokenUsage(10, 4)),
        (matching, TokenUsage(10, 4)),
        (matching, TokenUsage(10, 4)),
    ]
    return FakeLLMClient(responses)


def test_cli_json_analysis_uses_text_file_and_fake_llm(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    jd_file = tmp_path / "job.txt"
    jd_file.write_text(
        "Analyst needed with Python experience. The team builds reliable reporting "
        "and works with product partners on operational datasets.",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(openai_api_key="fake"))
    monkeypatch.setattr(cli, "create_llm_client", lambda _settings: fake_client())
    monkeypatch.setattr(cli, "_cache_path", lambda: tmp_path / "cache.sqlite")

    result = cli.main(
        ["analyze", str(FIXTURES / "resume.txt"), "--text-file", str(jd_file), "--json"]
    )

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert result == 0
    assert report["score"] == 100
    assert report["requirements"][0]["text"] == "Python"


def test_cli_url_path_uses_fetcher_adapter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeFetcher:
        def fetch(self, _url: str):
            return type(
                "FetchedJob",
                (),
                {
                    "text": "Analyst role requires Python and reporting. "
                    "The team works with operational data and product partners.",
                    "source": "json_ld",
                },
            )()

    monkeypatch.setattr(cli, "get_settings", lambda: Settings(openai_api_key="fake"))
    monkeypatch.setattr(cli, "create_llm_client", lambda _settings: fake_client())
    monkeypatch.setattr(cli, "_cache_path", lambda: tmp_path / "cache.sqlite")
    monkeypatch.setattr(cli, "JobFetcher", FakeFetcher)

    result = cli.main(
        ["analyze", str(FIXTURES / "resume.txt"), "--url", "https://example.com/job"]
    )

    assert result == 0
    assert "Match score: 100/100" in capsys.readouterr().out


def test_cli_requires_exactly_one_job_input() -> None:
    parser = cli.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["analyze", "resume.pdf"])
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "analyze",
                "resume.pdf",
                "--url",
                "https://example.com",
                "--text-file",
                "jd.txt",
            ]
        )


def test_eval_dataset_has_eight_valid_score_bands() -> None:
    cases = load_cases()

    assert len(cases) == 8
    assert len({case.case_id for case in cases}) == 8
    assert all(0 <= case.min_score <= case.max_score <= 100 for case in cases)
    assert all(
        len(case.resume_text) >= 200 and len(case.job_text) >= 200 for case in cases
    )


def test_eval_runner_skips_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("evals.run.get_settings", lambda: Settings(openai_api_key=None))

    result = run_evaluations()

    assert result == 0
    assert "SKIPPED" in capsys.readouterr().out
