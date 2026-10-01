import hashlib
import json

from jobfit.extraction.job import JobSource


def result_cache_key(
    resume_text: str,
    job_text: str,
    model: str,
    prompt_version: str,
    job_source: JobSource,
) -> str:
    payload = json.dumps(
        [resume_text, job_text, model, prompt_version, job_source],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
