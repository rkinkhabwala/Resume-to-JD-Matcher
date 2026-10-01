import io
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from jobfit.extraction.pii import redact_pii
from jobfit.extraction.resume import ResumeParseError, parse_resume

FIXTURES = Path(__file__).parents[1] / "fixtures" / "resumes"


def test_extracts_saved_text_resume() -> None:
    result = parse_resume((FIXTURES / "resume.txt").read_bytes())

    assert result.file_type == "txt"
    assert result.character_count >= 200
    assert "Senior Data Analyst" in result.text


def test_extracts_saved_second_resume() -> None:
    result = parse_resume((FIXTURES / "resume_second.txt").read_bytes())

    assert result.file_type == "txt"
    assert "Technical Project Manager" in result.text


def test_extracts_saved_pdf_resume() -> None:
    result = parse_resume((FIXTURES / "resume_pdf.pdf").read_bytes())

    assert result.file_type == "pdf"
    assert result.character_count >= 200
    assert "Product analyst" in result.text


def test_extracts_saved_docx_resume() -> None:
    result = parse_resume((FIXTURES / "resume_docx.docx").read_bytes())

    assert result.file_type == "docx"
    assert result.character_count >= 200
    assert "Morgan Lee" in result.text


def test_rejects_saved_scanned_pdf_with_clear_error() -> None:
    with pytest.raises(ResumeParseError, match="OCR is not supported") as error:
        parse_resume((FIXTURES / "resume_scanned.pdf").read_bytes())

    assert error.value.code == "SCANNED_PDF"


def test_rejects_encrypted_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    class EncryptedPDF:
        def __enter__(self) -> SimpleNamespace:
            return SimpleNamespace(
                doc=SimpleNamespace(encryption=(1, {})),
                pages=[],
            )

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(
        "jobfit.extraction.resume.pdfplumber.open",
        lambda _stream: EncryptedPDF(),
    )

    with pytest.raises(ResumeParseError) as error:
        parse_resume(b"%PDF-1.4\n")

    assert error.value.code == "ENCRYPTED_PDF"


def test_rejects_upload_over_five_megabytes() -> None:
    with pytest.raises(ResumeParseError, match="5 MB") as error:
        parse_resume(b"x" * (5 * 1024 * 1024 + 1))

    assert error.value.code == "FILE_TOO_LARGE"


def test_rejects_short_text_resume() -> None:
    with pytest.raises(ResumeParseError, match="at least 200 characters") as error:
        parse_resume(b"Too short to be a usable resume.")

    assert error.value.code == "INSUFFICIENT_TEXT"


def test_rejects_non_utf8_binary_as_text() -> None:
    with pytest.raises(ResumeParseError) as error:
        parse_resume(b"\xff\xfe\x00\x01" * 100)

    assert error.value.code == "UNSUPPORTED_FILE_TYPE"


def test_rejects_docx_archive_that_expands_past_twenty_megabytes() -> None:
    archive_bytes = io.BytesIO()
    with ZipFile(archive_bytes, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "x" * (20 * 1024 * 1024 + 1))

    with pytest.raises(ResumeParseError) as error:
        parse_resume(archive_bytes.getvalue())

    assert error.value.code == "FILE_TOO_LARGE"


def test_rejects_macro_enabled_docx() -> None:
    archive_bytes = io.BytesIO()
    with ZipFile(archive_bytes, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
        archive.writestr("word/vbaProject.bin", b"macro")

    with pytest.raises(ResumeParseError) as error:
        parse_resume(archive_bytes.getvalue())

    assert error.value.code == "MACROS_NOT_SUPPORTED"


def test_redacts_email_phone_and_street_address() -> None:
    result = redact_pii("Contact sam@example.com at 415-555-0188 or 123 Main Street.")

    assert result == (
        "Contact [REDACTED_EMAIL] at [REDACTED_PHONE] or [REDACTED_ADDRESS]."
    )
