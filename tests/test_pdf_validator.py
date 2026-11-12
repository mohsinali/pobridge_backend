"""Tests for bounded upload and PDF inspection."""

import pytest

from app.modules.ingestion.pdf_validator import (
    PDFPageLimitError,
    PDFTooLargeError,
    PDFValidationError,
    PDFValidator,
)
from tests.factories import make_pdf


def validator(*, max_size: int = 10 * 1024 * 1024, max_pages: int = 25) -> PDFValidator:
    return PDFValidator(max_size_bytes=max_size, max_pages=max_pages)


def test_valid_pdf() -> None:
    result = validator().validate(make_pdf(), "sample.pdf", "application/pdf")
    assert result.filename == "sample.pdf"
    assert result.page_count == 1


@pytest.mark.parametrize(
    ("content", "filename", "content_type", "message"),
    [
        (b"", "sample.pdf", "application/pdf", "empty"),
        (b"%PDF-invalid", "sample.txt", "application/pdf", ".pdf extension"),
        (b"%PDF-invalid", "sample.pdf", "text/plain", "application/pdf"),
        (b"not a pdf", "sample.pdf", "application/pdf", "signature"),
        (b"%PDF-1.7\ncorrupt", "sample.pdf", "application/pdf", "malformed"),
    ],
)
def test_invalid_uploads(
    content: bytes,
    filename: str,
    content_type: str,
    message: str,
) -> None:
    with pytest.raises(PDFValidationError, match=message):
        validator().validate(content, filename, content_type)


def test_encrypted_pdf_is_rejected() -> None:
    with pytest.raises(PDFValidationError, match="Encrypted"):
        validator().validate(make_pdf(encrypted=True), "secret.pdf", "application/pdf")


def test_file_size_limit_is_enforced() -> None:
    content = b"%PDF-" + (b"x" * (10 * 1024 * 1024))
    with pytest.raises(PDFTooLargeError):
        validator().validate(content, "large.pdf", "application/pdf")


def test_page_limit_is_enforced() -> None:
    with pytest.raises(PDFPageLimitError, match="2 pages"):
        validator(max_pages=2).validate(make_pdf(pages=3), "long.pdf", "application/pdf")
