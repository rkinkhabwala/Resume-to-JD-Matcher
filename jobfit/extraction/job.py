from __future__ import annotations

import json
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal

JobSource = Literal["json_ld", "ats_api", "generic_scrape", "pasted"]


@dataclass(frozen=True)
class ExtractedJob:
    title: str | None
    text: str


class _JSONLDScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: list[str] = []
        self._in_jsonld = False
        self._current: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            return
        attributes = dict(attrs)
        self._in_jsonld = (attributes.get("type") or "").split(";")[
            0
        ].strip().lower() == "application/ld+json"
        if self._in_jsonld:
            self._current = []

    def handle_data(self, data: str) -> None:
        if self._in_jsonld:
            self._current.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_jsonld:
            self.scripts.append("".join(self._current))
            self._current = []
            self._in_jsonld = False


class _HTMLTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if value:
            self.parts.append(value)


def html_to_text(value: str) -> str:
    parser = _HTMLTextParser()
    parser.feed(value)
    parser.close()
    return " ".join(" ".join(parser.parts).split())


def extract_jobposting_jsonld(html: str) -> ExtractedJob | None:
    parser = _JSONLDScriptParser()
    parser.feed(html)
    parser.close()
    for script in parser.scripts:
        try:
            payload = json.loads(script)
        except (json.JSONDecodeError, TypeError):
            continue
        for posting in _job_postings(payload):
            title = _value_to_text(posting.get("title")) or None
            sections = [
                _value_to_text(posting.get(field))
                for field in (
                    "description",
                    "responsibilities",
                    "qualifications",
                    "skills",
                    "experienceRequirements",
                    "educationRequirements",
                )
            ]
            body = "\n".join(section for section in sections if section)
            text = "\n".join(part for part in (title, body) if part)
            if text:
                return ExtractedJob(title=title, text=text)
    return None


def parse_ats_payload(payload: object, vendor: str) -> ExtractedJob | None:
    if isinstance(payload, list):
        payload = next((item for item in payload if isinstance(item, dict)), None)
    if not isinstance(payload, dict):
        return None

    title = (
        _value_to_text(
            payload.get("title") or payload.get("text") or payload.get("jobTitle")
        )
        or None
    )
    sections: list[str] = []
    if vendor == "greenhouse":
        sections.extend(
            _value_to_text(payload.get(field))
            for field in ("content", "description", "location")
        )
    elif vendor == "lever":
        sections.extend(
            _value_to_text(payload.get(field))
            for field in ("descriptionPlain", "description", "additional")
        )
        lists = payload.get("lists")
        if isinstance(lists, list):
            for item in lists:
                if isinstance(item, dict):
                    sections.extend(
                        _value_to_text(item.get(field)) for field in ("text", "content")
                    )
                else:
                    sections.append(_value_to_text(item))
    elif vendor == "ashby":
        sections.extend(
            _value_to_text(payload.get(field))
            for field in ("description", "descriptionHtml", "team")
        )
    else:
        sections.extend(
            _value_to_text(payload.get(field))
            for field in ("description", "descriptionHtml", "descriptionPlain")
        )

    body = "\n".join(section for section in sections if section)
    text = "\n".join(part for part in (title, body) if part)
    return ExtractedJob(title=title, text=text) if text else None


def _job_postings(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, list):
        return [posting for item in payload for posting in _job_postings(item)]
    if not isinstance(payload, dict):
        return []

    schema_type = payload.get("@type")
    type_names = schema_type if isinstance(schema_type, list) else [schema_type]
    is_job_posting = any(
        str(name).rsplit("/", 1)[-1].rsplit("#", 1)[-1] == "JobPosting"
        for name in type_names
    )
    if is_job_posting:
        return [payload]

    return [posting for item in payload.values() for posting in _job_postings(item)]


def _value_to_text(value: object) -> str:
    if isinstance(value, str):
        return html_to_text(value)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "\n".join(text for item in value if (text := _value_to_text(item)))
    if isinstance(value, dict):
        for field in ("name", "value", "text", "description"):
            if field in value:
                return _value_to_text(value[field])
    return ""
