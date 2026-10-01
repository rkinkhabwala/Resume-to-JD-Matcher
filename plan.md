# JobFit Implementation Plan

## Architecture

```text
Streamlit UI ──HTTP──> FastAPI API ──> PostgreSQL
                           │                 │
                           ├── enqueue ──> Redis/arq worker
                           │                    │
                           │                    ├── jobfit core
                           │                    ├── OpenAI-compatible LLMClient
                           │                    └── result cache (SQLite in M4;
                           │                         Redis/Postgres adapter in M6)
                           └── SSE/status reads <── worker progress

CLI ──> jobfit core (local synchronous analysis)
```

`jobfit/` is the framework-independent domain package: schemas, parsing/scoring
contracts, confidence, evidence verification, and orchestration. It must not import
FastAPI, Streamlit, SQLAlchemy, Redis, or arq. The API, worker, CLI, and UI depend on
the core; the core never depends on those surfaces. File/network adapters are outside
the core. The CLI calls the core directly. API submissions are asynchronous from M6;
the UI communicates only with the API.

## Package Layout

```text
jobfit/
  __init__.py
  config.py                 # pydantic-settings: score weights/cap, confidence weights,
                            # limits, model, timeout, privacy and retention settings
  errors.py                 # domain errors and stable error codes
  schemas/
    llm.py                  # strict structured-output models for LLM steps
    report.py               # public analysis report models
  extraction/
    resume.py               # PDF, DOCX, TXT validation and extraction
    job.py                  # JSON-LD, ATS, generic extraction contracts
    pii.py                  # local PII redaction
  llm/
    protocol.py             # LLMClient protocol and usage value object
    openai_client.py        # sole module importing the OpenAI SDK
    fake.py                 # deterministic test double
  scoring/
    pipeline.py             # five-step orchestration
    experience.py           # date ranges and union-of-months calculations
    evidence.py             # quote verification and verdict downgrades
    score.py                # weighted score, knockout cap, keyword coverage
    confidence.py           # confidence signals and reasons
  cache/
    protocol.py
    sqlite.py               # M4 local result cache
api/
  app.py
  routes/
worker/
  app.py
  tasks.py
ui/
  app.py
cli.py
prompts/
  v1/
    job_analysis.txt
    resume_analysis.txt
    matching.txt
tests/
  fixtures/
  unit/
  integration/
evals/
  cases/
docs/
  decisions.md
  deployment.md
```

M1 will create the minimum skeleton for its gates. Later milestones add the listed
modules when they become needed; this layout is a target, not a requirement to create
empty files early.

## Pydantic Models

All structured LLM output fields are required. Nullable values use `T | None` and
remain required keys; no defaults are used for OpenAI strict structured outputs. Keep
JSON-schema constraints to supported types and enums; enforce lengths, counts, date
validity, and cross-field rules in Python after parsing.

### Step 1: Job analysis

- `JobAnalysis`: `role_title: str`, `seniority: str`, `requirements: list[JobRequirement]`.
- `JobRequirement`: `id: str`, `text: str`, `category: Literal["skill", "experience", "education", "certification", "domain", "soft_skill", "other"]`, `importance: Literal["must_have", "nice_to_have"]`, `min_years: int | None`, `importance_inferred: bool`.
- Validate at most 25 requirements and de-duplicate normalized requirement text in Python. Seniority stays free text because the spec gives no canonical seniority vocabulary.

### Step 2: Resume analysis

- `ResumeAnalysis`: `skills: list[str]`, `roles: list[ResumeRole]`, `education: list[EducationEntry]`, `certifications: list[str]`.
- `ResumeRole`: `title: str`, `employer: str | None`, `start_date: str | None`, `end_date: str | None`.
- `EducationEntry`: `degree: str`, `institution: str | None`, `field: str | None`, `completion_date: str | None`.
- Dates use ISO year-month (`YYYY-MM`) when known. Missing or unparseable dates remain `None`; Python does not invent dates.

### Step 3: Matching (three independent runs)

- `MatchingResult`: `matches: list[RequirementMatch]`.
- `RequirementMatch`: `requirement_id: str`, `verdict: Literal["met", "partial", "not_met", "unclear"]`, `evidence: list[str]`, `evidence_type: Literal["explicit", "inferred"]`, `reason: str`.
- Validate one result per requirement, evidence quote word-count (maximum 25 words), and IDs in Python. Each prompt gets the same static instructions/schema prefix and clearly tagged untrusted resume/job text last. Run three times, shuffling requirement order each time.

### Evidence verification output

- `VerifiedMatch` is the internal form of a `RequirementMatch` after each quote has been checked against the source resume using `rapidfuzz.fuzz.partial_ratio >= 90`.
- Drop failed quotes. If a `met` or `partial` result has no verified quote left, downgrade it to `unclear` and increment the downgrade count. This verification is deterministic Python logic, not a fourth LLM judgment.

### Final report

- `AnalysisReport`: `score: int`, `confidence: Confidence`, `summary: str`, `requirements: list[ReportRequirement]`, `strengths: list[str]`, `gaps: list[str]`, `resume_suggestions: list[str]`, `keyword_coverage: float`, `model: str`, `prompt_version: str`, `usage: TokenUsage`, `timings_ms: dict[str, int]`, `warnings: list[str]`.
- `Confidence`: `value: float`, `label: Literal["High", "Medium", "Low"]`, `reasons: list[str]`.
- `ReportRequirement`: `id: str`, `text: str`, `category: str`, `importance: Literal["must_have", "nice_to_have"]`, `importance_inferred: bool`, `min_years: int | None`, `verdict: Literal["met", "partial", "not_met", "unclear"]`, `evidence: list[str]`, `evidence_type: Literal["explicit", "inferred"]`, `reason: str`.
- `TokenUsage`: `input_tokens: int`, `output_tokens: int`, `total_tokens: int`, `estimated_cost_usd: float | None`.
- `warnings` carries safe processing notes such as input truncation; raw text and PII are never included in logs. Model/prompt metadata and timings describe the selected representative run plus aggregate pipeline timing.
- The report uses the median-scoring run's verified requirements and score, so the displayed requirements explain the displayed score. The median of three scores is itself one of the three scores.
- Summary, strengths, gaps, and truthful resume suggestions are assembled from the verified requirement results with deterministic templates; they do not add another LLM step or imply qualifications absent from the resume.

## Scoring and Confidence

### Deterministic score

For each verified requirement, points are `met=1.0`, `partial=0.5`, `unclear=0.25`,
`not_met=0`. Weights are `must_have=3`, `nice_to_have=1`.

```text
raw_score = round(100 * sum(weight * points) / sum(weight))
score = min(raw_score, 65) if any must-have experience/education/certification
        requirement is not_met, otherwise raw_score
```

Must-have/nice-to-have weights (`3` and `1`) and the knockout cap (`65`) are
configuration settings, not literals in the scoring algorithm. Confidence signal
weights are likewise configured. Example: two
must-haves (`met`, `partial`) and one nice-to-have (`not_met`) yield
`round(100 * (3*1 + 3*0.5 + 1*0) / 7) = 64`; no cap applies. If the second
must-have is instead a failed must-have certification, the raw score is `43` and the
cap still cannot raise it. Example of the cap binding: three must-haves (`met`, `met`,
`not_met` experience) and one nice-to-have (`met`) yield raw `70`, capped to `65`.

Experience is the union of dated role intervals, to avoid double-counting overlapping
jobs. An open end date means the current month; missing/invalid dates add no duration.
For an explicit `min_years`, compare the requirement to documented total experience
in whole months (`months >= min_years * 12`). If below minimum, the matching verdict
for that requirement is deterministically set to `not_met`; the score and knockout
cap then follow the normal rules. This conservative policy is recorded in
`docs/decisions.md`; role relevance remains part of the evidence-backed LLM judgment,
not a guessed Python classification.

Hard-skill keyword coverage is deterministic: use distinct normalized tokens and
phrases from `skill` requirements, remove a small fixed stop-word set, and count a
keyword present only when its normalized phrase occurs in the normalized resume text.
Coverage is `100 * present / total`; an empty keyword set returns `0` and a reason is
available to the report/UI. Do not add a second LLM score.

### Confidence

Each signal is in `[0, 1]`; final confidence is a weighted average:

```text
confidence = 0.30 * consistency
           + 0.30 * evidence_strength
           + 0.25 * input_quality
           + 0.15 * verification
```

- Consistency uses the three post-verification scores and spread `max - min`: 1.0 at
  spread `<= 5`, 0.0 at spread `>= 20`, linear between: `(20 - spread) / 15`.
- Evidence strength is the fraction of all requirements with an `explicit` evidence
  type and a non-`unclear` verdict; an empty set is 0.
- Input quality is `0.40 * requirement_quality + 0.40 * resume_parse_quality +
  0.20 * job_source_quality`. Requirement quality is `min(count / 8, 1)`. Resume
  parse quality is the fraction of extracted-text, role/date, and section checks that
  pass, defined in tests and surfaced as parse metadata. Job source quality is 1.0
  for pasted/JSON-LD/ATS API, 0.5 for generic scrape, and 0 for unavailable/blocked.
- Verification is verified quote count / submitted quote count; if there are no
  submitted quotes, it is 0.
- Labels: High `>= 0.75`, Medium `>= 0.50`, otherwise Low. Reasons explain the
  weakest signals (for example, few requirements, low parse quality, broad run
  spread, or unverified evidence), rather than presenting confidence as candidate
  quality.

Example: spread 8 gives consistency `12/15 = 0.8`; explicit evidence share `0.75`,
input quality `0.8`, and verification `0.9` yield
`0.30*0.8 + 0.30*0.75 + 0.25*0.8 + 0.15*0.9 = 0.7975`, High.

## API Endpoints

All endpoints are versioned under `/api/v1`; this resolves the unversioned endpoint
examples in section 8 in favor of the explicit production API versioning requirement.

- `GET /health`: liveness only; no dependency checks.
- `GET /ready`: readiness checks for configured dependencies; M1 initially checks app/config, with DB/Redis checks added in M6.
- `POST /api/v1/extract-job`: accepts a URL, returns extracted text and source for user editing; blocked/unreadable links return a stable problem response and tell the UI to use paste input.
- `POST /api/v1/analyses`: accepts resume upload and either URL-derived or pasted job text; returns `202 Accepted`, analysis ID, and status URL. A supplied edited text is authoritative over a fetched preview.
- `GET /api/v1/analyses/{analysis_id}`: status/progress and, on completion, report or problem response.
- `GET /api/v1/analyses/{analysis_id}/events`: optional SSE progress events (`extracting`, `analysing_job`, `analysing_resume`, `matching`, `scoring`, terminal state).
- M8 adds authenticated history and hard-delete endpoints for an analysis/account.

Errors use `application/problem+json` with stable `code`, `title`, `status`, `detail`,
and `instance` fields. Submission idempotency is based on a hash of normalized input,
model, and prompt version. Resume text is not persisted; only the report and required
operational metadata are retained.

## Prompt Designs

Version prompts together under `prompts/v1/`; bump `prompt_version` and run evals for
any prompt or scoring-weight change. Shared prompt structure:

1. Static system instructions: role, schema/task, evidence rules, job-relevance-only
   policy, prohibited protected-trait inference, and explicit instruction that tagged
   content is untrusted data and never instructions.
2. Static schema/instructions before variable content for automatic prefix caching.
3. Variable content last, in `<job_description>...</job_description>` and
   `<resume_text>...</resume_text>` tags. Escape/encode tag-like content so untrusted
   text cannot close its wrapper.

Step prompts ask only for their schema: job requirements and inferred-importance flag;
resume facts and dates; requirement-by-requirement verdicts with verbatim quotes of at
most 25 words and one-sentence rationale. Matching prompt says met needs direct
evidence, related-but-different skills are partial, and neither confirmation nor
contradiction is unclear. No prompt asks for a score. Use the same static prompt
version across all three shuffled matching runs.

## Milestone Checklist

- [x] M0 — Plan drafted and approved.
- [ ] M1 — Skeleton: uv project, config, quality tools, JSON request-ID logging,
  FastAPI health/readiness, CI. Gate: `uv run ruff check . && uv run ruff format --check . && uv run mypy jobfit && uv run pytest`, then verify uvicorn `/health`.
- [ ] M2 — Input extraction: guarded PDF/DOCX/TXT parsing, safe job fetching, ATS/JSON-LD/generic extraction, robots/SSRF protections, and local PII redaction. Gate: saved fixtures and SSRF tests.
- [ ] M3 — LLM layer: protocol, OpenAI Responses structured output, fake, retry/refusal/usage behavior, versioned prompts and injection boundaries. Gate: fake-client unit coverage and a credential-gated integration test.
- [ ] M4 — Scoring pipeline: three shuffled runs, quote verification, date-derived experience, deterministic score/caps/keywords/confidence, final report, SQLite cache. Gate: table-driven math, edge cases and injection tests; run the required full check command.
- [ ] M5 — CLI and evals: `jobfit analyze`, 8–10 expected-band pairs, `make eval` score/spread/cost table. Gate: CLI invocation and eval summary; report actual eval results.
- [ ] M6 — Async API/worker/persistence: PostgreSQL, SQLAlchemy 2, Alembic, Redis, arq, v1 submit/poll/SSE, idempotency, problem responses. Gate: API integration tests using Testcontainers, including failures.
- [ ] M7 — Streamlit UI: complete link/paste/edit/analyze/report/download flow, API-only. Gate: local end-to-end flow via compose.
- [ ] M8 — Production hardening: authentication, rate/cost budgets, circuit breaker, caps, security controls, history/deletion/retention, telemetry/metrics. Gate: specified auth, 429, budget, deletion and circuit-breaker tests.
- [ ] M9 — Delivery: non-root multi-stage image, full compose, coverage/security/image CI, eval workflows, mocked Locust load test, README and deployment guide. Gate: clean-clone compose flow and green CI.

After every implementation milestone, run exactly:

```sh
uv run ruff check . && uv run ruff format --check . && uv run mypy jobfit && uv run pytest
```

Commit once per completed milestone with a conventional commit subject. Do not commit
secrets, `.env`, uploads, or raw resume/job text. Integration/eval tests requiring
OpenAI are skipped without `OPENAI_API_KEY`; ordinary unit tests use the fake client
and saved fixtures only.

## Decisions and Open Questions

Implementation decisions and their alternatives/rationale are recorded in
[`docs/decisions.md`](docs/decisions.md). The initial resolved choices are confidence
weights, experience calculation, representative-run report selection, API versioning,
and the fixed hard-skill coverage interpretation.

Open questions retained for implementation-time verification, not M0 blockers:

- Confirm the configured OpenAI model available to the user; `.env.example` will give
  a sensible configurable default, with no model name embedded in code.
- Select a deployment target from the spec's examples; Render is the planned simplest
  guide unless deployment constraints emerge.
- Exact price-table values depend on the chosen model and must be documented/configured
  rather than assumed in scoring.
- Robots policy and ATS endpoints can vary by host; tests will use saved fixtures and
  mocked transports, with failures falling back to the paste path.