from cache.sqlite_cache import SQLiteResultCache
from jobfit.cache.key import result_cache_key
from jobfit.schemas.report import (
    AnalysisReport,
    Confidence,
    ReportTokenUsage,
)


def report() -> AnalysisReport:
    return AnalysisReport(
        score=75,
        confidence=Confidence(
            value=0.8, label="High", reasons=["Consistent evidence."]
        ),
        summary="The score is evidence-backed.",
        requirements=[],
        strengths=[],
        gaps=[],
        resume_suggestions=[],
        keyword_coverage=50.0,
        model="test-model",
        prompt_version="v1",
        usage=ReportTokenUsage(
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            estimated_cost_usd=None,
        ),
        timings_ms={"total": 10},
        warnings=[],
    )


def test_sqlite_cache_round_trips_report_without_storing_input(tmp_path) -> None:
    cache_path = tmp_path / "cache.sqlite"
    cache = SQLiteResultCache(cache_path)
    value = report()

    cache.set("hashed-input", value)

    assert cache.get("hashed-input") == value
    stored_bytes = cache_path.read_bytes()
    assert b"hashed-input" in stored_bytes
    assert b"private resume text" not in stored_bytes


def test_cache_key_changes_for_source_model_or_prompt() -> None:
    args = ("resume", "job", "model", "v1")
    pasted = result_cache_key(*args, "pasted")

    assert result_cache_key(*args, "generic_scrape") != pasted
    assert result_cache_key("other resume", *args[1:], "pasted") != pasted
    assert result_cache_key(*args[:3], "v2", "pasted") != pasted
