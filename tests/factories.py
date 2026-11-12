"""Small deterministic fixtures used by extraction tests."""

from decimal import Decimal

import pymupdf

from app.schemas.purchase_order import (
    Address,
    Customer,
    LineItem,
    ModelObservation,
    OrderTotals,
    PurchaseOrder,
    ShippingDetails,
    StructuredPurchaseOrderExtraction,
)


def make_pdf(*, pages: int = 1, encrypted: bool = False) -> bytes:
    document = pymupdf.open()
    for page_number in range(pages):
        page = document.new_page()
        page.insert_text((72, 72), f"Purchase Order page {page_number + 1}")
    options: dict[str, object] = {}
    if encrypted:
        options = {
            "encryption": pymupdf.PDF_ENCRYPT_AES_256,
            "owner_pw": "owner-password",
            "user_pw": "user-password",
        }
    content = document.tobytes(**options)
    document.close()
    return content


def make_extraction(
    *,
    po_number: str | None = "PO-10482",
    customer_name: str | None = "ABC Manufacturing",
    line_items: list[LineItem] | None = None,
    po_date: str | None = "2026-11-10",
    requested_delivery_date: str | None = "2026-11-20",
    model_warnings: list[ModelObservation] | None = None,
) -> StructuredPurchaseOrderExtraction:
    if line_items is None:
        line_items = [
            LineItem(
                line_number=1,
                part_number="BRK-1001",
                description="Brake Assembly",
                quantity=Decimal("10"),
                uom="EA",
                unit_price=Decimal("125.00"),
                line_total=Decimal("1250.00"),
            )
        ]
    return StructuredPurchaseOrderExtraction(
        data=PurchaseOrder(
            po_number=po_number,
            po_date=po_date,
            requested_delivery_date=requested_delivery_date,
            customer=Customer(name=customer_name),
            bill_to=Address(name=None, address=None),
            ship_to=Address(name=None, address=None),
            line_items=line_items,
            shipping=ShippingDetails(
                carrier=None,
                method=None,
                third_party_account=None,
                notes=None,
            ),
            totals=OrderTotals(
                subtotal=Decimal("1250.00"),
                tax=None,
                shipping_cost=None,
                grand_total=Decimal("1250.00"),
                currency="USD",
            ),
        ),
        warnings=model_warnings or [],
    )
