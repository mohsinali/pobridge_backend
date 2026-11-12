"""Purchase-order extraction workflow orchestration."""

import logging
from datetime import date
from time import perf_counter
from uuid import uuid4

from app.modules.extraction.providers.base import ExtractionProvider
from app.modules.ingestion.pdf_validator import PDFValidator
from app.schemas.purchase_order import (
    ExtractionMetadata,
    ExtractionResponse,
    ExtractionWarning,
    PurchaseOrder,
)

logger = logging.getLogger(__name__)


class ExtractionService:
    def __init__(self, *, validator: PDFValidator, provider: ExtractionProvider) -> None:
        self.validator = validator
        self.provider = provider

    async def extract(
        self,
        *,
        pdf_content: bytes,
        filename: str | None,
        content_type: str | None,
    ) -> ExtractionResponse:
        started_at = perf_counter()
        validated = self.validator.validate(pdf_content, filename, content_type)
        provider_result = await self.provider.extract(validated.content, validated.filename)
        warnings = self._build_warnings(provider_result.data)
        warnings.extend(
            ExtractionWarning(
                code=observation.code,
                field=observation.field,
                message=observation.message,
                source="model",
            )
            for observation in provider_result.warnings
        )
        processing_time_ms = round((perf_counter() - started_at) * 1000)
        logger.info(
            "Purchase order extraction completed document_id=%s pages=%s duration_ms=%s",
            document_id := str(uuid4()),
            validated.page_count,
            processing_time_ms,
        )
        return ExtractionResponse(
            document_id=document_id,
            schema_version="1.0",
            status="completed",
            data=provider_result.data,
            warnings=warnings,
            metadata=ExtractionMetadata(
                filename=validated.filename,
                model=self.provider.model_name,
                processing_time_ms=processing_time_ms,
                page_count=validated.page_count,
            ),
        )

    @staticmethod
    def _build_warnings(data: PurchaseOrder) -> list[ExtractionWarning]:
        warnings: list[ExtractionWarning] = []

        def add(code: str, field: str, message: str) -> None:
            warnings.append(
                ExtractionWarning(
                    code=code,
                    field=field,
                    message=message,
                    source="deterministic",
                )
            )

        if not data.po_number:
            add("MISSING_PO_NUMBER", "po_number", "PO number could not be identified.")
        if not data.customer.name:
            add("MISSING_CUSTOMER_NAME", "customer.name", "Customer name could not be identified.")
        if not data.line_items:
            add("NO_LINE_ITEMS", "line_items", "No purchase order line items were identified.")

        for index, item in enumerate(data.line_items):
            prefix = f"line_items[{index}]"
            if item.quantity is None:
                add("MISSING_LINE_ITEM_QUANTITY", f"{prefix}.quantity", "Line item quantity is missing.")
            if not item.part_number:
                add("MISSING_LINE_ITEM_PART_NUMBER", f"{prefix}.part_number", "Line item part number is missing.")
            if item.unit_price is None:
                add("MISSING_LINE_ITEM_UNIT_PRICE", f"{prefix}.unit_price", "Line item unit price is missing.")

        for field_name in ("po_date", "requested_delivery_date"):
            value = getattr(data, field_name)
            if value:
                try:
                    date.fromisoformat(value)
                except ValueError:
                    add(
                        "AMBIGUOUS_OR_INVALID_DATE",
                        field_name,
                        f"Date value '{value}' is ambiguous or invalid and was not interpreted.",
                    )
        return warnings
