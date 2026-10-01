import sys
from html import escape
from pathlib import Path
from typing import Literal

PromptStep = Literal["job_analysis", "resume_analysis", "matching"]
UntrustedTag = Literal["job_description", "resume_text", "requirements"]
PROMPT_VERSION = "v1"
_PROMPT_ROOT = Path(__file__).resolve().parents[2] / "prompts"
_INSTALLED_PROMPT_ROOT = Path(sys.prefix) / "share" / "jobfit" / "prompts"


def load_system_prompt(step: PromptStep, version: str = PROMPT_VERSION) -> str:
    relative_path = Path(version) / f"{step}.txt"
    for root in (_PROMPT_ROOT, _INSTALLED_PROMPT_ROOT):
        prompt_path = root / relative_path
        if prompt_path.is_file():
            return prompt_path.read_text(encoding="utf-8")
    raise FileNotFoundError(f"Prompt file is missing: {relative_path}")


def tag_untrusted_data(tag: UntrustedTag, value: str) -> str:
    return f"<{tag}>{escape(value, quote=False)}</{tag}>"


def render_job_analysis_user(job_text: str) -> str:
    return tag_untrusted_data("job_description", job_text)


def render_resume_analysis_user(resume_text: str) -> str:
    return tag_untrusted_data("resume_text", resume_text)


def render_matching_user(
    job_text: str,
    resume_text: str,
    requirements_json: str,
) -> str:
    return "\n\n".join(
        (
            tag_untrusted_data("job_description", job_text),
            tag_untrusted_data("resume_text", resume_text),
            tag_untrusted_data("requirements", requirements_json),
        )
    )
