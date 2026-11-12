"""Replaceable extraction provider contract and domain errors."""

from abc import ABC, abstractmethod

from app.schemas.purchase_order import StructuredPurchaseOrderExtraction


class ExtractionProviderError(RuntimeError):
    """Base provider failure safe to translate at the API boundary."""


class ProviderConfigurationError(ExtractionProviderError):
    pass


class ProviderAuthenticationError(ExtractionProviderError):
    pass


class ProviderTimeoutError(ExtractionProviderError):
    pass


class ProviderUnavailableError(ExtractionProviderError):
    pass


class InvalidProviderResponseError(ExtractionProviderError):
    pass


class ExtractionProvider(ABC):
    model_name: str

    @abstractmethod
    async def extract(self, pdf_content: bytes, filename: str) -> StructuredPurchaseOrderExtraction:
        """Extract typed data from validated PDF bytes."""
