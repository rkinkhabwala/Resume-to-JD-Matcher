import re

_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)")
_STREET_ADDRESS = re.compile(
    r"\b\d{1,6}\s+[A-Z0-9.'#-]+(?:\s+[A-Z0-9.'#-]+){0,4}\s+"
    r"(?:street|st\.?|avenue|ave\.?|road|rd\.?|boulevard|blvd\.?|"
    r"lane|ln\.?|drive|dr\.?|court|ct\.?|way|place|pl\.?)\b"
    r"(?:\s+(?:apt\.?|apartment|unit|suite|ste\.?|#)\s*[A-Z0-9-]+)?",
    re.IGNORECASE,
)


def _replace_phone(match: re.Match[str]) -> str:
    digits = sum(character.isdigit() for character in match.group())
    if 10 <= digits <= 15:
        return "[REDACTED_PHONE]"
    return match.group()


def redact_pii(text: str) -> str:
    redacted = _EMAIL.sub("[REDACTED_EMAIL]", text)
    redacted = _PHONE.sub(_replace_phone, redacted)
    return _STREET_ADDRESS.sub("[REDACTED_ADDRESS]", redacted)
