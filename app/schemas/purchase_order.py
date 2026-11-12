"""Typed purchase-order extraction schemas."""

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, WithJsonSchema, field_validator


DecimalString = Annotated[
    Decimal,
    WithJsonSchema(
        {
            "type": "string",
            "pattern": r"^-?(?:0|[1-9]\d*)(?:\.\d+)?$",
        }
    ),
]


class StrictSchema(BaseModel):
    """Base model compatible with OpenAI strict Structured Outputs."""

    model_config = ConfigDict(extra="forbid")


class Customer(StrictSchema):
    name: str | None


class Address(StrictSchema):
    name: str | None
    address: str | None


class LineItem(StrictSchema):
    line_number: int | None
    part_number: str | None
    description: str | None
    quantity: DecimalString | None
    uom: str | None
    unit_price: DecimalString | None
    line_total: DecimalString | None


class ShippingDetails(StrictSchema):
    carrier: str | None
    method: str | None
    third_party_account: str | None
    notes: str | None


class OrderTotals(StrictSchema):
    subtotal: DecimalString | None
    tax: DecimalString | None
    shipping_cost: DecimalString | None
    grand_total: DecimalString | None
    currency: str | None


class PurchaseOrder(StrictSchema):
    po_number: str | None
    po_date: str | None
    requested_delivery_date: str | None
    customer: Customer
    bill_to: Address
    ship_to: Address
    line_items: list[LineItem]
    shipping: ShippingDetails
    totals: OrderTotals

    @field_validator("po_date", "requested_delivery_date")
    @classmethod
    def normalize_date_text(cls, value: str | None) -> str | None:
        """Keep source date text for warning generation; normalize blanks to null."""
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ModelObservation(StrictSchema):
    """A source ambiguity or omission explicitly observed by the model."""

    code: str
    field: str | None
    message: str


class StructuredPurchaseOrderExtraction(StrictSchema):
    """Provider-facing schema parsed directly by the OpenAI SDK."""

    data: PurchaseOrder
    warnings: list[ModelObservation]


class ExtractionWarning(StrictSchema):
    code: str
    field: str | None
    message: str
    source: Literal["deterministic", "model"]


class ExtractionMetadata(StrictSchema):
    filename: str
    model: str
    processing_time_ms: int
    page_count: int


class ExtractionResponse(StrictSchema):
    document_id: UUID
    schema_version: Literal["1.0"]
    status: Literal["completed"]
    data: PurchaseOrder
    warnings: list[ExtractionWarning]
    metadata: ExtractionMetadata
