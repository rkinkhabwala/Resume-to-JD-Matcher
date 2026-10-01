# Decisions

## Confidence signal weights

- **Decision:** Weight consistency 0.30, evidence strength 0.30, input quality 0.25,
  and verification 0.15.
- **Alternatives:** Equal weights; favor input quality; leave weights unspecified.
- **Why:** The spec requires a weighted average but gives no weights. Consistency and
  evidence directly measure judgment reliability, while input and quote verification
  remain substantial independent checks. The weights sum to 1 and are explicit,
  testable, and reported in `plan.md`.

## Experience calculation and enforcement

- **Decision:** Compute the union of dated role intervals in whole months, avoiding
  overlap double-counting. An open end date extends through the current month.
  Deterministically set a numeric `min_years` requirement to `not_met` only when all
  listed role start dates are parseable and the documented total is below threshold;
  otherwise leave the evidence-based verdict unchanged.
- **Alternatives:** Sum each role independently; ask the LLM to estimate years; count
  missing dates as zero experience and force `not_met`; never use computed years to
  change a verdict.
- **Why:** Python, not the LLM, must compute years. Unioning intervals is conservative
  and prevents concurrent jobs from inflating experience. A below-threshold rule makes
  the stated numeric requirement operational and allows the specified knockout cap to
  work when evidence is complete. Missing dates do not prove a shortfall; preserving
  the model's evidence-based verdict in that case avoids contradicting the `unclear`
  rule. Domain relevance remains an evidence-backed matching judgment because the
  spec does not define a deterministic role-to-requirement mapping.

## Three-run report selection

- **Decision:** Return the verified requirements and score from the median-scoring
  matching run; calculate confidence spread across all three post-verification scores.
- **Alternatives:** Majority-vote every verdict and recompute score; union evidence
  across runs; return the highest or lowest run.
- **Why:** The median of three is one of the observed scores, so selecting that run
  keeps the explanation and displayed score internally consistent without inventing
  an aggregation rule the spec does not specify.

## API versioning

- **Decision:** Put job extraction, asynchronous analysis submission, status, and SSE
  under `/api/v1`; do not add a separate synchronous `/api/analyze` endpoint.
- **Alternatives:** Preserve the unversioned section-8 endpoints as aliases; make a
  synchronous route alongside the async API.
- **Why:** The production requirements explicitly require versioning and asynchronous
  processing for a 30–90 second operation. One canonical surface avoids duplicate
  behavior; extraction remains a separate preview/edit step.

## Keyword coverage semantics

- **Decision:** Derive distinct normalized hard-skill tokens/phrases from `skill`
  requirements, match normalized phrases exactly as substrings of the resume, and use
  zero when there are no keywords.
- **Alternatives:** Add an NLP/keyphrase dependency; use fuzzy or semantic matching;
  count every word in the entire job description.
- **Why:** The spec requires deterministic coverage and discourages unrequested
  dependencies. Limiting terms to analyzed skill requirements is auditable and avoids
  inflating coverage with generic job-description words.

## Job network adapter boundary

- **Decision:** Put HTTP fetching, DNS/SSRF checks, robots.txt handling, and generic
  page extraction in top-level `jobfetch/`; keep byte-based resume parsing, PII
  redaction, and pure payload parsing in `jobfit/`.
- **Alternatives:** Put all extraction under `jobfit/`; move all document parsing to
  adapters.
- **Why:** The core must remain free of web/network imports, and deterministic
  document/domain parsing is reusable across CLI, API, and worker callers.

## Unavailable robots.txt

- **Decision:** Fail closed when robots.txt cannot be fetched or returns a non-success
  status other than 404/410; a missing robots file permits the fetch.
- **Alternatives:** Treat every retrieval failure as no restrictions; retry with
  another user agent.
- **Why:** The spec requires respecting robots.txt and forbids bypassing site controls.
  Failing closed avoids scraping when permission cannot be established, while 404/410
  follows the convention that no robots rules are published.

## Azure OpenAI selection

- **Decision:** Select the SDK client with `OPENAI_API_TYPE=openai|azure`; use
  `OPENAI_BASE_URL` for the OpenAI-compatible base URL or Azure endpoint and
  `OPENAI_API_VERSION` for Azure's API version.
- **Alternatives:** Guess Azure from the base URL hostname; add separate Azure-specific
  endpoint/key settings.
- **Why:** The spec requires both OpenAI-compatible base URLs and the official
  `AzureOpenAI` client behind one interface. An explicit provider avoids brittle URL
  inference while reusing the requested API key and endpoint settings.

## SQLite cache adapter boundary

- **Decision:** Keep a storage-neutral cache protocol and key helper in `jobfit/`, but
  implement SQLite in a top-level adapter outside the core.
- **Alternatives:** Import `sqlite3` from `jobfit/cache`; defer caching until Postgres
  and Redis are introduced.
- **Why:** M4 requires an SQLite result cache while the architecture rule forbids DB
  imports in `jobfit/`. The adapter satisfies both and keeps scoring independent of
  storage.

## Cache source key

- **Decision:** Include job source in addition to resume text, job text, model, and
  prompt version when computing the result-cache key.
- **Alternatives:** Use only the four named values from the spec; invalidate all cache
  entries whenever source policy changes.
- **Why:** Identical text from a pasted source and a generic scrape has different
  confidence quality. Omitting source could return a cached report with incorrect
  confidence for otherwise identical input.