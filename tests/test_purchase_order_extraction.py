"""API and service tests using an injected provider; no external calls."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.v1.purchase_orders import get_extraction_provider
from app.main import app
from app.modules.extraction.providers.base import (
    ExtractionProvider,
    InvalidProviderResponseError,
    ProviderAuthenticationError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.schemas.purchase_order import LineItem, ModelObservation, StructuredPurchaseOrderExtraction
from tests.factories import make_extraction, make_pdf


class FakeProvider(ExtractionProvider):
    model_name = "fake-document-model"

    def __init__(
        self,
        result: StructuredPurchaseOrderExtraction | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result or make_extraction()
        self.error = error
        self.calls: list[tuple[bytes, str]] = []

    async def extract(self, pdf_content: bytes, filename: str) -> StructuredPurchaseOrderExtraction:
        self.calls.append((pdf_content, filename))
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def client_and_provider() -> tuple[TestClient, FakeProvider]:
    provider = FakeProvider()
    app.dependency_overrides[get_extraction_provider] = lambda: provider
    with TestClient(app) as client:
        yield client, provider
    app.dependency_overrides.clear()


def post_pdf(client: TestClient, content: bytes | None = None, filename: str = "sample-po.pdf"):
    return client.post(
        "/api/v1/purchase-orders/extract",
        files={"file": (filename, content or make_pdf(), "application/pdf")},
    )


def test_successful_structured_response_and_decimal_serialization(
    client_and_provider: tuple[TestClient, FakeProvider],
) -> None:
    client, provider = client_and_provider
    response = post_pdf(client)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["schema_version"] == "1.0"
    assert payload["data"]["po_number"] == "PO-10482"
    assert payload["data"]["line_items"][0]["unit_price"] == "125.00"
    assert payload["metadata"]["filename"] == "sample-po.pdf"
    assert payload["metadata"]["model"] == "fake-document-model"
    assert payload["metadata"]["page_count"] == 1
    assert len(provider.calls) == 1


def test_missing_file_returns_422() -> None:
    with TestClient(app) as client:
        response = client.post("/api/v1/purchase-orders/extract")
    assert response.status_code == 422


def test_openapi_documents_multipart_endpoint_and_errors() -> None:
    operation = app.openapi()["paths"]["/api/v1/purchase-orders/extract"]["post"]
    assert "multipart/form-data" in operation["requestBody"]["content"]
    assert {"200", "400", "413", "422", "502", "503", "504"} <= set(operation["responses"])


def test_multi_page_pdf_is_passed_to_provider_once(
    client_and_provider: tuple[TestClient, FakeProvider],
) -> None:
    client, provider = client_and_provider
    response = post_pdf(client, make_pdf(pages=3))
    assert response.status_code == 200
    assert response.json()["metadata"]["page_count"] == 3
    assert len(provider.calls) == 1


def test_multiple_line_items_and_missing_optional_fields(
    client_and_provider: tuple[TestClient, FakeProvider],
) -> None:
    client, provider = client_and_provider
    provider.result = make_extraction(
        requested_delivery_date=None,
        line_items=[
            LineItem(
                line_number=1,
                part_number="001",
                description=None,
                quantity=Decimal("2.50"),
                uom="LB",
                unit_price=Decimal("4.00"),
                line_total=None,
            ),
            LineItem(
                line_number=2,
                part_number="002",
                description="Second",
                quantity=Decimal("1"),
                uom="EA",
                unit_price=Decimal("8.00"),
                line_total=Decimal("8.00"),
            ),
        ],
    )
    payload = post_pdf(client).json()
    assert payload["data"]["requested_delivery_date"] is None
    assert payload["data"]["line_items"][0]["part_number"] == "001"
    assert payload["data"]["line_items"][0]["quantity"] == "2.50"
    assert len(payload["data"]["line_items"]) == 2


@pytest.mark.parametrize(
    ("result", "codes"),
    [
        (make_extraction(po_number=None), {"MISSING_PO_NUMBER"}),
        (make_extraction(customer_name=None), {"MISSING_CUSTOMER_NAME"}),
        (make_extraction(line_items=[]), {"NO_LINE_ITEMS"}),
    ],
)
def test_required_extraction_warnings(
    client_and_provider: tuple[TestClient, FakeProvider],
    result: StructuredPurchaseOrderExtraction,
    codes: set[str],
) -> None:
    client, provider = client_and_provider
    provider.result = result
    response_codes = {warning["code"] for warning in post_pdf(client).json()["warnings"]}
    assert codes <= response_codes


def test_line_item_date_and_model_warnings_are_distinguished(
    client_and_provider: tuple[TestClient, FakeProvider],
) -> None:
    client, provider = client_and_provider
    provider.result = make_extraction(
        po_date="11/12/26",
        line_items=[
            LineItem(
                line_number=1,
                part_number=None,
                description="Unknown item",
                quantity=None,
                uom=None,
                unit_price=None,
                line_total=None,
            )
        ],
        model_warnings=[
            ModelObservation(
                code="UNCLEAR_DATE_LABEL",
                field="po_date",
                message="The source date label is unclear.",
            )
        ],
    )
    warnings = post_pdf(client).json()["warnings"]
    by_code = {warning["code"]: warning for warning in warnings}
    assert by_code["AMBIGUOUS_OR_INVALID_DATE"]["source"] == "deterministic"
    assert by_code["MISSING_LINE_ITEM_QUANTITY"]["source"] == "deterministic"
    assert by_code["MISSING_LINE_ITEM_PART_NUMBER"]["source"] == "deterministic"
    assert by_code["MISSING_LINE_ITEM_UNIT_PRICE"]["source"] == "deterministic"
    assert by_code["UNCLEAR_DATE_LABEL"]["source"] == "model"


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (InvalidProviderResponseError("invalid response"), 502),
        (ProviderTimeoutError("timed out"), 504),
        (ProviderUnavailableError("rate limited"), 503),
        (ProviderAuthenticationError("authentication failed"), 503),
    ],
)
def test_provider_failures_are_mapped_without_internal_details(
    error: Exception,
    expected_status: int,
) -> None:
    provider = FakeProvider(error=error)
    app.dependency_overrides[get_extraction_provider] = lambda: provider
    with TestClient(app) as client:
        response = post_pdf(client)
    app.dependency_overrides.clear()
    assert response.status_code == expected_status
    assert "traceback" not in response.text.lower()


def test_missing_api_key_is_graceful_and_health_remains_available() -> None:
    app.dependency_overrides.clear()
    with TestClient(app) as client:
        extraction = post_pdf(client)
        health = client.get("/api/v1/health")
    assert extraction.status_code == 503
    assert extraction.json()["detail"]["code"] == "EXTRACTION_NOT_CONFIGURED"
    assert health.status_code == 200
