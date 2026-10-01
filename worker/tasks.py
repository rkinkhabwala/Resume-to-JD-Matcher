from __future__ import annotations

import asyncio

from api.store import analysis_store


async def run_analysis(
    analysis_id: str,
    *,
    resume_text: str,
    job_text: str,
    source: str = "pasted",
) -> None:
    """Simulate the async pipeline for a single analysis job.

    This keeps the milestone focused on API and worker orchestration without
    pulling in Redis or Postgres dependencies. The production-ready persistence
    layer is introduced in later milestones.
    """
    del resume_text, source

    analysis_store.update(
        analysis_id,
        status="extracting",
        progress="extracting",
        message="Extracting resume text and validating the input.",
    )
    await asyncio.sleep(0.05)

    analysis_store.update(
        analysis_id,
        status="analysing_job",
        progress="analysing_job",
        message="Analyzing the job description and extracting requirements.",
    )
    await asyncio.sleep(0.05)

    analysis_store.update(
        analysis_id,
        status="matching",
        progress="matching",
        message="Matching resume strengths and gaps against the job requirements.",
    )
    await asyncio.sleep(0.05)

    analysis_store.update(
        analysis_id,
        status="scoring",
        progress="scoring",
        message="Scoring and verifying confidence signals.",
    )
    await asyncio.sleep(0.05)

    result = {
        "score": 88,
        "confidence": {
            "value": 0.83,
            "label": "High",
            "reasons": [
                "The resume covers the primary stack and role-level experience.",
                (
                    "The job description is short but specific enough for a "
                    "reliable match."
                ),
            ],
        },
        "summary": (
            "This candidate is a strong match for the Python-focused role. "
            "Core skills and years of experience line up with the posted requirements, "
            "with room to strengthen the job-specific experience narrative."
        ),
        "requirements": [
            {
                "id": "req-1",
                "text": "Python",
                "importance": "must_have",
                "verdict": "met",
                "evidence": ["Python, SQL, AWS, five years."],
                "reason": "The resume explicitly lists Python and relevant experience.",
            },
            {
                "id": "req-2",
                "text": "SQL",
                "importance": "must_have",
                "verdict": "met",
                "evidence": ["Python, SQL, AWS, five years."],
                "reason": (
                    "The resume explicitly names SQL as part of the candidate profile."
                ),
            },
            {
                "id": "req-3",
                "text": "AWS",
                "importance": "nice_to_have",
                "verdict": "partial",
                "evidence": ["AWS"],
                "reason": (
                    "AWS appears in the resume, but the role likely expects "
                    "deeper cloud depth."
                ),
            },
        ],
        "strengths": ["Python experience", "SQL proficiency", "Cloud familiarity"],
        "gaps": ["Deeper systems design work", "Production-scale AWS ownership"],
        "resume_suggestions": [
            "Lead with the Python and SQL experience in the summary.",
            "Add one concrete systems-design example to reinforce seniority.",
        ],
        "keyword_coverage": 0.75,
        "model": "gpt-4.1-mini",
        "prompt_version": "v1",
    }

    analysis_store.update(
        analysis_id,
        status="completed",
        progress="completed",
        message="Analysis complete.",
        result=result,
    )
