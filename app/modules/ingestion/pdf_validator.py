"""Bounded upload reading and defensive PDF inspection."""

from dataclasses import dataclass
from pathlib import PurePath

import pymupdf
from fastapi import UploadFile


class PDFValidationError(ValueError):
    """Base error for an invalid PDF upload."""

    status_code = 400
    code = "INVALID_PDF"


class PDFTooLargeError(PDFValidationError):
    status_code = 413
    code = "PDF_TOO_LARGE"


class PDFPageLimitError(PDFValidationError):
    code = "PDF_PAGE_LIMIT_EXCEEDED"


@dataclass(frozen=True, slots=True)
class ValidatedPDF:
    content: bytes
    filename: str
    page_count: int


async def read_upload_bounded(upload: UploadFile, max_size_bytes: int) -> bytes:
    """Read at most one byte beyond the configured limit."""
    content = await upload.read(max_size_bytes + 1)
    if len(content) > max_size_bytes:
        raise PDFTooLargeError("The PDF exceeds the configured upload size limit.")
    return content


class PDFValidator:
    def __init__(self, *, max_size_bytes: int, max_pages: int) -> None:
        self.max_size_bytes = max_size_bytes
        self.max_pages = max_pages

    def validate(self, content: bytes, filename: str | None, content_type: str | None) -> ValidatedPDF:
        safe_filename = PurePath((filename or "").replace("\\", "/")).name
        if not safe_filename or PurePath(safe_filename).suffix.lower() != ".pdf":
            raise PDFValidationError("The uploaded file must use a .pdf extension.")
        if content_type != "application/pdf":
            raise PDFValidationError("The uploaded file must have application/pdf content type.")
        if not content:
            raise PDFValidationError("The uploaded PDF is empty.")
        if len(content) > self.max_size_bytes:
            raise PDFTooLargeError("The PDF exceeds the configured upload size limit.")
        if not content.startswith(b"%PDF-"):
            raise PDFValidationError("The uploaded file does not have a valid PDF signature.")

        try:
            document = pymupdf.open(stream=content, filetype="pdf")
            with document:
                if document.needs_pass:
                    raise PDFValidationError("Encrypted or password-protected PDFs are not supported.")
                if not document.is_pdf or document.page_count < 1 or document.is_repaired:
                    raise PDFValidationError("The uploaded PDF is malformed or unreadable.")
                if document.page_count > self.max_pages:
                    raise PDFPageLimitError(
                        f"The PDF exceeds the configured limit of {self.max_pages} pages."
                    )
                for page_number in range(document.page_count):
                    document.load_page(page_number)
                page_count = document.page_count
        except PDFValidationError:
            raise
        except (pymupdf.FileDataError, RuntimeError, ValueError) as exc:
            raise PDFValidationError("The uploaded PDF is malformed or unreadable.") from exc

        return ValidatedPDF(content=content, filename=safe_filename, page_count=page_count)
