"""OpenAI provider request construction tests with a fully local mock."""

import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.modules.extraction.providers.base import (
    InvalidProviderResponseError,
    ProviderConfigurationError,
)
from app.modules.extraction.providers.openai import OpenAIExtractionProvider
from app.schemas.purchase_order import StructuredPurchaseOrderExtraction
from tests.factories import make_extraction, make_pdf


class FakeResponses:
    def __init__(self, response) -> None:
        self.response = response
        self.calls: list[dict] = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def make_provider(response) -> tuple[OpenAIExtractionProvider, FakeResponses]:
    provider = OpenAIExtractionProvider(api_key="test-key", model="test-model", timeout_seconds=2)
    responses = FakeResponses(response)
    provider._client = SimpleNamespace(responses=responses)  # type: ignore[assignment]
    return provider, responses


def test_provider_sends_one_base64_pdf_structured_request() -> None:
    expected = make_extraction()
    provider, responses = make_provider(
        SimpleNamespace(status="completed", output_parsed=expected, usage=None)
    )
    result = asyncio.run(provider.extract(make_pdf(), "sample.pdf"))

    assert result == expected
    assert len(responses.calls) == 1
    request = responses.calls[0]
    assert request["model"] == "test-model"
    assert request["store"] is False
    assert request["text_format"] is StructuredPurchaseOrderExtraction
    assert "If freight is TBD, unknown, or otherwise unspecified" in request["instructions"]
    assert "Normalize `5,820.00` to `5820.00`" in request["instructions"]
    assert "Do not blindly remove commas" in request["instructions"]
    assert "return null for that field and add an extraction warning" in request["instructions"]
    file_input = request["input"][0]["content"][0]
    assert file_input["filename"] == "sample.pdf"
    assert file_input["file_data"].startswith("data:application/pdf;base64,")


def test_provider_rejects_incomplete_model_output() -> None:
    provider, _ = make_provider(
        SimpleNamespace(status="incomplete", output_parsed=None, usage=None)
    )
    with pytest.raises(InvalidProviderResponseError):
        asyncio.run(provider.extract(make_pdf(), "sample.pdf"))


def test_provider_decimal_schema_matches_pydantic_validation_and_logs_paths(caplog) -> None:
    schema = StructuredPurchaseOrderExtraction.model_json_schema()
    unit_price_schema = schema["$defs"]["LineItem"]["properties"]["unit_price"]["anyOf"][0]
    assert unit_price_schema == {
        "type": "string",
        "pattern": r"^-?(?:0|[1-9]\d*)(?:\.\d+)?$",
    }

    payload = make_extraction().model_dump(mode="json")
    payload["data"]["line_items"][0]["unit_price"] = "$125.00"
    with pytest.raises(ValidationError) as validation:
        StructuredPurchaseOrderExtraction.model_validate(payload)

    provider, _ = make_provider(validation.value)
    with caplog.at_level("WARNING", logger="app.modules.extraction.providers.openai"):
        with pytest.raises(InvalidProviderResponseError):
            asyncio.run(provider.extract(make_pdf(), "sample.pdf"))

    assert "error_type=ValidationError" in caplog.text
    assert "data.line_items.0.unit_price" in caplog.text
    assert "openai_http_status=None" in caplog.text


def test_provider_checks_configuration_only_when_extraction_is_requested() -> None:
    provider = OpenAIExtractionProvider(api_key=None, model="test-model", timeout_seconds=2)
    with pytest.raises(ProviderConfigurationError):
        asyncio.run(provider.extract(make_pdf(), "sample.pdf"))
