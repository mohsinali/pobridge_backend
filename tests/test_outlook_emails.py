"""Targeted Outlook Inbox tests; all Microsoft interactions are mocked."""

import json
import time

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.api.v1.outlook import SESSION_COOKIE, require_service
from app.main import app
from app.modules.integrations.crypto import SecretCipher
from app.modules.integrations.outlook import OutlookIntegrationService
from app.modules.integrations.repository import (
    IntegrationConnection,
    SQLiteIntegrationRepository,
)


SESSION_ID = "test-session-with-at-least-thirty-two-characters"


class FakeMicrosoftClient:
    def __init__(self) -> None:
        self.message_tokens: list[str] = []
        self.refresh_tokens: list[str] = []
        self.graph_status: int | None = None

    async def refresh_access_token(self, refresh_token: str) -> dict[str, object]:
        self.refresh_tokens.append(refresh_token)
        return {
            "access_token": "refreshed-access-token",
            "refresh_token": "rotated-refresh-token",
            "expires_in": 3600,
        }

    async def get_inbox_messages(self, access_token: str) -> dict[str, object]:
        self.message_tokens.append(access_token)
        if self.graph_status is not None:
            request = httpx.Request("GET", "https://graph.microsoft.com/v1.0/me/messages")
            response = httpx.Response(self.graph_status, request=request)
            raise httpx.HTTPStatusError("Graph error", request=request, response=response)
        return {
            "value": [
                {
                    "id": "AAMk+exact/id==",
                    "from": {
                        "emailAddress": {
                            "name": "John Smith",
                            "address": "john@example.com",
                        }
                    },
                    "subject": "Purchase Order",
                    "receivedDateTime": "2026-11-16T10:30:00Z",
                    "hasAttachments": True,
                },
                {
                    "id": "second-message",
                    "from": None,
                    "subject": None,
                    "receivedDateTime": "2026-11-16T09:30:00Z",
                    "hasAttachments": False,
                },
            ]
        }


def _service(tmp_path, *, connected: bool = True, expired: bool = False):
    repository = SQLiteIntegrationRepository(str(tmp_path / "integrations.db"))
    cipher = SecretCipher(Fernet.generate_key().decode())
    microsoft = FakeMicrosoftClient()
    service = OutlookIntegrationService(
        repository=repository,
        cipher=cipher,
        microsoft=microsoft,
        client_id="client-id",
        authority="https://login.microsoftonline.com/common",
        redirect_uri="http://localhost:8000/api/v1/integrations/outlook/callback",
        transaction_ttl_seconds=600,
    )
    if connected:
        credentials = {
            "access_token": "original-access-token",
            "refresh_token": "original-refresh-token",
            "expires_in": 3600,
            "obtained_at": int(time.time()) - (7200 if expired else 0),
        }
        assert repository.save_connection(
            IntegrationConnection(
                provider="outlook",
                owner_session_hash=service.hash_secret(SESSION_ID),
                account_id="account-1",
                email="person@outlook.com",
                display_name="Outlook User",
                encrypted_credentials=cipher.encrypt(json.dumps(credentials)),
            )
        )
    return service, microsoft


@pytest.fixture
def email_client(tmp_path):
    service, microsoft = _service(tmp_path)
    app.dependency_overrides[require_service] = lambda: service
    with TestClient(app) as client:
        client.cookies.set(
            SESSION_COOKIE,
            SESSION_ID,
            path="/api/v1/integrations/outlook",
        )
        yield client, microsoft
    app.dependency_overrides.clear()


def test_get_emails_returns_normalized_latest_messages(email_client) -> None:
    client, microsoft = email_client

    response = client.get("/api/v1/integrations/outlook/emails")

    assert response.status_code == 200
    assert response.json() == {
        "provider": "outlook",
        "emails": [
            {
                "id": "AAMk+exact/id==",
                "sender_name": "John Smith",
                "sender_email": "john@example.com",
                "subject": "Purchase Order",
                "received_at": "2026-11-16T10:30:00Z",
                "has_attachments": True,
            },
            {
                "id": "second-message",
                "sender_name": None,
                "sender_email": None,
                "subject": None,
                "received_at": "2026-11-16T09:30:00Z",
                "has_attachments": False,
            },
        ],
    }
    assert microsoft.message_tokens == ["original-access-token"]


def test_get_emails_refreshes_expired_access_token(tmp_path) -> None:
    service, microsoft = _service(tmp_path, expired=True)
    app.dependency_overrides[require_service] = lambda: service
    try:
        with TestClient(app) as client:
            client.cookies.set(
                SESSION_COOKIE, SESSION_ID, path="/api/v1/integrations/outlook"
            )
            response = client.get("/api/v1/integrations/outlook/emails")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert microsoft.refresh_tokens == ["original-refresh-token"]
    assert microsoft.message_tokens == ["refreshed-access-token"]


def test_get_emails_rejects_disconnected_account(tmp_path) -> None:
    service, _ = _service(tmp_path, connected=False)
    app.dependency_overrides[require_service] = lambda: service
    try:
        with TestClient(app) as client:
            client.cookies.set(
                SESSION_COOKIE, SESSION_ID, path="/api/v1/integrations/outlook"
            )
            response = client.get("/api/v1/integrations/outlook/emails")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json() == {"detail": "Outlook account is not connected"}


def test_get_emails_maps_graph_failure_without_leaking_details(email_client) -> None:
    client, microsoft = email_client
    microsoft.graph_status = 500

    response = client.get("/api/v1/integrations/outlook/emails")

    assert response.status_code == 502
    assert response.json() == {"detail": "Microsoft Graph request failed"}
    assert "access-token" not in response.text
