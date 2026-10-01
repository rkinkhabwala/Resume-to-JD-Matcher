from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from cache.sqlite_cache import SQLiteResultCache
from jobfetch.fetcher import JobFetcher, JobFetchError
from jobfit.config import get_settings
from jobfit.extraction.job import JobSource
from jobfit.extraction.resume import ResumeParseError, parse_resume
from jobfit.llm.openai_client import (
    LLMConfigurationError,
    LLMResponseError,
    create_llm_client,
)
from jobfit.scoring.pipeline import AnalysisPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobfit")
    commands = parser.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser("analyze", help="Compare a resume with a job")
    analyze.add_argument("resume", type=Path, help="PDF, DOCX, or TXT resume")
    job_input = analyze.add_mutually_exclusive_group(required=True)
    job_input.add_argument("--url", help="Public job posting URL")
    job_input.add_argument("--text-file", type=Path, help="File containing job text")
    analyze.add_argument("--json", action="store_true", help="Print the JSON report")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "analyze":
        return _analyze(args)
    return 2


def _analyze(args: argparse.Namespace) -> int:
    try:
        settings = get_settings()
        resume = parse_resume(args.resume.read_bytes())
        if args.url:
            job = JobFetcher().fetch(args.url)
            job_text = job.text
            job_source: JobSource = job.source
        else:
            if args.text_file is None:
                raise ValueError("Provide either --url or --text-file.")
            job_text = args.text_file.read_text(encoding="utf-8")
            job_source = "pasted"

        client = create_llm_client(settings)
        report = AnalysisPipeline(
            client,
            settings,
            model=settings.llm_model,
            cache=SQLiteResultCache(_cache_path()),
        ).analyze(resume.text, job_text, job_source)
    except (
        JobFetchError,
        LLMConfigurationError,
        LLMResponseError,
        OSError,
        ResumeParseError,
        UnicodeError,
        ValueError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        print(f"Match score: {report.score}/100")
        print(f"Confidence: {report.confidence.label} ({report.confidence.value:.2f})")
        print(report.summary)
        for reason in report.confidence.reasons:
            print(f"- {reason}")
    return 0


def _cache_path() -> Path:
    return Path.home() / ".cache" / "jobfit" / "results.sqlite"


if __name__ == "__main__":
    raise SystemExit(main())
