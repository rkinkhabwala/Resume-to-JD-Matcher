import json
from pathlib import Path

from pydantic import BaseModel, TypeAdapter

from jobfit.config import get_settings
from jobfit.llm.openai_client import create_llm_client
from jobfit.scoring.pipeline import AnalysisPipeline

_CASES_PATH = Path(__file__).with_name("cases.json")


class EvalCase(BaseModel):
    case_id: str
    resume_text: str
    job_text: str
    min_score: int
    max_score: int


class EvalResult(BaseModel):
    case_id: str
    score: int
    spread: int
    cost_usd: float
    passed: bool


def load_cases() -> list[EvalCase]:
    payload = json.loads(_CASES_PATH.read_text(encoding="utf-8"))
    return TypeAdapter(list[EvalCase]).validate_python(payload)


def run_evaluations() -> int:
    settings = get_settings()
    if not settings.openai_api_key:
        print("SKIPPED: set OPENAI_API_KEY to run real-model evaluations.")
        return 0

    client = create_llm_client(settings)
    pipeline = AnalysisPipeline(client, settings, model=settings.llm_model)
    results: list[EvalResult] = []
    cases = load_cases()
    print(
        f"{'CASE':<28} {'SCORE':>5} {'BAND':>11} {'SPREAD':>7} {'COST USD':>11}  RESULT"
    )
    for case in cases:
        outcome = pipeline.analyze_with_diagnostics(
            case.resume_text,
            case.job_text,
            "pasted",
        )
        report = outcome.report
        spread = max(outcome.run_scores) - min(outcome.run_scores)
        passed = case.min_score <= report.score <= case.max_score
        cost = report.usage.estimated_cost_usd or 0.0
        result = EvalResult(
            case_id=case.case_id,
            score=report.score,
            spread=spread,
            cost_usd=cost,
            passed=passed,
        )
        results.append(result)
        band = f"{case.min_score}-{case.max_score}"
        outcome_label = "PASS" if passed else "FAIL"
        print(
            f"{case.case_id:<28} {report.score:>5} {band:>11} "
            f"{spread:>7} {cost:>11.6f}  {outcome_label}"
        )

    total_cost = sum(result.cost_usd for result in results)
    passed_count = sum(result.passed for result in results)
    print(
        f"TOTAL: {passed_count}/{len(results)} bands passed; "
        f"estimated cost ${total_cost:.6f}"
    )
    return 0 if passed_count == len(results) else 1


def main() -> int:
    return run_evaluations()


if __name__ == "__main__":
    raise SystemExit(main())
