"""Purchase order upload and extraction endpoint."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.core.config import Settings, get_settings
from app.modules.extraction.providers.base import (
    ExtractionProvider,
    InvalidProviderResponseError,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.modules.extraction.providers.openai import OpenAIExtractionProvider
from app.modules.extraction.service import ExtractionService
from app.modules.ingestion.pdf_validator import PDFValidationError, PDFValidator, read_upload_bounded
from app.schemas.purchase_order import ExtractionResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/purchase-orders", tags=["purchase orders"])


def get_extraction_provider(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ExtractionProvider:
    return OpenAIExtractionProvider(
        api_key=settings.OPENAI_API_KEY,
        model=settings.OPENAI_MODEL,
        timeout_seconds=settings.OPENAI_TIMEOUT_SECONDS,
    )


def get_extraction_service(
    settings: Annotated[Settings, Depends(get_settings)],
    provider: Annotated[ExtractionProvider, Depends(get_extraction_provider)],
) -> ExtractionService:
    return ExtractionService(
        validator=PDFValidator(
            max_size_bytes=settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024,
            max_pages=settings.MAX_PDF_PAGES,
        ),
        provider=provider,
    )


@router.post(
    "/extract",
    response_model=ExtractionResponse,
    status_code=status.HTTP_200_OK,
    summary="Extract a purchase order from a PDF",
    description=(
        "Upload one PDF using the `file` multipart field. The document must be no larger "
        "than the configured upload limit (10 MB by default) and must contain no more than "
        "the configured page limit (25 pages by default)."
    ),
    responses={
        400: {"description": "Invalid, encrypted, malformed, non-PDF, or over-page-limit PDF"},
        413: {"description": "PDF exceeds the configured upload size limit"},
        422: {"description": "Missing multipart file field or invalid request"},
        502: {"description": "The provider returned an invalid structured response"},
        503: {"description": "Provider configuration, authentication, rate limit, or availability failure"},
        504: {"description": "The extraction provider timed out"},
    },
)
async def extract_purchase_order(
    file: Annotated[UploadFile, File(description="One purchase order PDF")],
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[ExtractionService, Depends(get_extraction_service)],
) -> ExtractionResponse:
    try:
        content = await read_upload_bounded(file, settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024)
        return await service.extract(
            pdf_content=content,
            filename=file.filename,
            content_type=file.content_type,
        )
    except PDFValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}) from exc
    except ProviderConfigurationError as exc:
        logger.warning("Extraction provider configuration failure")
        raise HTTPException(status_code=503, detail={"code": "EXTRACTION_NOT_CONFIGURED", "message": str(exc)}) from exc
    except ProviderAuthenticationError as exc:
        logger.warning("Extraction provider authentication failure")
        raise HTTPException(
            status_code=503,
            detail={"code": "EXTRACTION_AUTHENTICATION_FAILED", "message": str(exc)},
        ) from exc
    except ProviderTimeoutError as exc:
        logger.warning("Extraction provider timeout")
        raise HTTPException(status_code=504, detail={"code": "EXTRACTION_TIMEOUT", "message": str(exc)}) from exc
    except ProviderUnavailableError as exc:
        logger.warning("Extraction provider unavailable: %s", type(exc.__cause__).__name__)
        raise HTTPException(status_code=503, detail={"code": "EXTRACTION_UNAVAILABLE", "message": str(exc)}) from exc
    except InvalidProviderResponseError as exc:
        logger.warning(
            "Extraction provider returned an invalid response error_type=%s cause_type=%s",
            type(exc).__name__,
            type(exc.__cause__).__name__ if exc.__cause__ is not None else None,
        )
        raise HTTPException(status_code=502, detail={"code": "INVALID_EXTRACTION_RESPONSE", "message": str(exc)}) from exc
