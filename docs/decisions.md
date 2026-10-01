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
  overlap double-counting. For a numeric `min_years`, deterministically set that
  requirement to `not_met` when documented total experience is below the threshold.
  Missing/invalid dates do not contribute; an open end date extends through the
  current month.
- **Alternatives:** Sum each role independently; ask the LLM to estimate years; use
  experience only as explanatory context without changing verdicts.
- **Why:** Python, not the LLM, must compute years. Unioning intervals is conservative
  and prevents concurrent jobs from inflating experience. A below-threshold rule makes
  the stated numeric requirement operational and allows the specified knockout cap to
  work. Domain relevance remains an evidence-backed matching judgment because the
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