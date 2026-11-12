"""OpenAI Responses API extraction provider."""

import base64
import logging

import openai
from openai import AsyncOpenAI
from pydantic import ValidationError

from app.modules.extraction.prompts import (
    PURCHASE_ORDER_EXTRACTION_INSTRUCTIONS,
    PURCHASE_ORDER_EXTRACTION_REQUEST,
)
from app.modules.extraction.providers.base import (
    ExtractionProvider,
    InvalidProviderResponseError,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.schemas.purchase_order import StructuredPurchaseOrderExtraction

logger = logging.getLogger(__name__)


def _validation_paths(exc: ValidationError) -> list[str]:
    return [".".join(str(part) for part in error["loc"]) for error in exc.errors(include_input=False)]


def _http_status(exc: Exception) -> int | None:
    return getattr(getattr(exc, "response", None), "status_code", None)


class OpenAIExtractionProvider(ExtractionProvider):
    def __init__(self, *, api_key: str | None, model: str, timeout_seconds: float) -> None:
        self.model_name = model
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._client: AsyncOpenAI | None = None

    async def extract(self, pdf_content: bytes, filename: str) -> StructuredPurchaseOrderExtraction:
        if not self._api_key or not self._api_key.strip():
            raise ProviderConfigurationError("OpenAI extraction is not configured.")
        if not self.model_name.strip():
            raise ProviderConfigurationError("The OpenAI model is not configured.")
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                timeout=self._timeout_seconds,
                max_retries=0,
            )
        encoded_pdf = base64.b64encode(pdf_content).decode("ascii")
        try:
            response = await self._client.responses.parse(
                model=self.model_name,
                instructions=PURCHASE_ORDER_EXTRACTION_INSTRUCTIONS,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_file",
                                "filename": filename,
                                "file_data": f"data:application/pdf;base64,{encoded_pdf}",
                                "detail": "low",
                            },
                            {"type": "input_text", "text": PURCHASE_ORDER_EXTRACTION_REQUEST},
                        ],
                    }
                ],
                text_format=StructuredPurchaseOrderExtraction,
                store=False,
            )
        except openai.AuthenticationError as exc:
            raise ProviderAuthenticationError("OpenAI authentication failed.") from exc
        except openai.APITimeoutError as exc:
            raise ProviderTimeoutError("OpenAI extraction timed out.") from exc
        except (openai.RateLimitError, openai.APIConnectionError, openai.InternalServerError) as exc:
            raise ProviderUnavailableError("OpenAI extraction is temporarily unavailable.") from exc
        except openai.APIStatusError as exc:
            logger.warning(
                "OpenAI extraction request failed error_type=%s validation_paths=[] openai_http_status=%s",
                type(exc).__name__,
                exc.status_code,
            )
            raise ProviderUnavailableError("OpenAI extraction is temporarily unavailable.") from exc
        except (openai.LengthFinishReasonError, openai.ContentFilterFinishReasonError) as exc:
            logger.warning(
                "OpenAI structured output incomplete error_type=%s validation_paths=[] openai_http_status=%s",
                type(exc).__name__,
                _http_status(exc),
            )
            raise InvalidProviderResponseError("OpenAI did not return a complete structured response.") from exc
        except ValidationError as exc:
            logger.warning(
                "OpenAI structured output validation failed error_type=%s validation_paths=%s "
                "openai_http_status=%s",
                type(exc).__name__,
                _validation_paths(exc),
                _http_status(exc),
            )
            raise InvalidProviderResponseError("OpenAI returned an invalid structured response.") from exc
        except (ValueError, TypeError) as exc:
            logger.warning(
                "OpenAI structured output parsing failed error_type=%s validation_paths=[] "
                "openai_http_status=%s",
                type(exc).__name__,
                _http_status(exc),
            )
            raise InvalidProviderResponseError("OpenAI returned an invalid structured response.") from exc

        parsed = response.output_parsed
        if response.status != "completed" or parsed is None:
            incomplete_details = getattr(response, "incomplete_details", None)
            logger.warning(
                "OpenAI structured output unavailable error_type=%s validation_paths=[] "
                "response_status=%s incomplete_reason=%s",
                "MissingParsedOutput" if parsed is None else "IncompleteResponse",
                response.status,
                getattr(incomplete_details, "reason", None),
            )
            raise InvalidProviderResponseError("OpenAI did not return a completed structured response.")

        usage = getattr(response, "usage", None)
        if usage is not None:
            logger.info(
                "OpenAI extraction usage input_tokens=%s output_tokens=%s",
                getattr(usage, "input_tokens", None),
                getattr(usage, "output_tokens", None),
            )
        return parsed
