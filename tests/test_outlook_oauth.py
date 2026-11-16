"""Targeted Outlook OAuth tests; all Microsoft interactions are mocked."""

import sqlite3
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.api.v1.outlook import require_service
from app.main import app
from app.modules.integrations.crypto import SecretCipher
from app.modules.integrations.outlook import OutlookIntegrationService
from app.modules.integrations.repository import SQLiteIntegrationRepository


class FakeMicrosoftClient:
    def __init__(self) -> None:
        self.exchanges: list[tuple[str, str]] = []

    async def exchange_code(self, *, code: str, code_verifier: str) -> dict[str, object]:
        self.exchanges.append((code, code_verifier))
        return {
            "access_token": "mock-access-token",
            "refresh_token": "mock-refresh-token",
            "token_type": "Bearer",
            "scope": "User.Read Mail.Read",
            "expires_in": 3600,
        }

    async def get_account(self, access_token: str) -> dict[str, str]:
        assert access_token == "mock-access-token"
        return {
            "id": "account-1",
            "displayName": "Outlook User",
            "mail": "person@outlook.com",
            "userPrincipalName": "person@outlook.com",
        }


@pytest.fixture
def oauth_setup(tmp_path):
    database_path = tmp_path / "integrations.db"
    microsoft = FakeMicrosoftClient()
    service = OutlookIntegrationService(
        repository=SQLiteIntegrationRepository(str(database_path)),
        cipher=SecretCipher(Fernet.generate_key().decode()),
        microsoft=microsoft,
        client_id="client-id",
        authority="https://login.microsoftonline.com/common",
        redirect_uri="http://localhost:8000/api/v1/integrations/outlook/callback",
        transaction_ttl_seconds=600,
    )
    app.dependency_overrides[require_service] = lambda: service
    with TestClient(app, follow_redirects=False) as client:
        yield client, microsoft, database_path
    app.dependency_overrides.clear()


def _start(client: TestClient) -> tuple[str, dict[str, list[str]]]:
    response = client.get("/api/v1/integrations/outlook/connect")
    assert response.status_code == 307
    query = parse_qs(urlparse(response.headers["location"]).query)
    return query["state"][0], query


def test_connect_uses_common_authority_pkce_scopes_and_protected_cookie(oauth_setup) -> None:
    client, _, _ = oauth_setup
    state, query = _start(client)

    assert state
    assert query["client_id"] == ["client-id"]
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert len(query["code_challenge"][0]) == 43
    assert set(query["scope"][0].split()) == {
        "openid",
        "profile",
        "email",
        "User.Read",
        "Mail.Read",
        "offline_access",
    }
    response = client.get("/api/v1/integrations/outlook/connect")
    assert response.headers["location"].startswith(
        "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?"
    )
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


def test_callback_persists_encrypted_tokens_then_status_and_disconnect(oauth_setup) -> None:
    client, microsoft, database_path = oauth_setup
    state, _ = _start(client)

    callback = client.get(
        "/api/v1/integrations/outlook/callback", params={"code": "auth-code", "state": state}
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == "http://localhost:3000/integrations/outlook?outlook=success"
    assert microsoft.exchanges[0][0] == "auth-code"
    assert len(microsoft.exchanges[0][1]) >= 43

    status_response = client.get("/api/v1/integrations/outlook/status")
    assert status_response.status_code == 200
    assert status_response.json() == {"connected": True, "email": "person@outlook.com"}

    raw_database = database_path.read_bytes()
    assert b"mock-access-token" not in raw_database
    assert b"mock-refresh-token" not in raw_database
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM integration_connections").fetchone()[0] == 1

    disconnected = client.post(
        "/api/v1/integrations/outlook/disconnect",
        headers={"Origin": "http://localhost:3000"},
    )
    assert disconnected.status_code == 200
    assert disconnected.json() == {"connected": False, "email": None}
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM integration_connections").fetchone()[0] == 0


def test_callback_rejects_replay_and_invalid_state_without_new_microsoft_call(oauth_setup) -> None:
    client, microsoft, _ = oauth_setup
    state, _ = _start(client)

    first = client.get(
        "/api/v1/integrations/outlook/callback", params={"code": "first", "state": state}
    )
    replay = client.get(
        "/api/v1/integrations/outlook/callback", params={"code": "second", "state": state}
    )
    invalid = client.get(
        "/api/v1/integrations/outlook/callback", params={"code": "third", "state": "invalid"}
    )

    assert first.headers["location"].endswith("outlook=success")
    assert replay.headers["location"].endswith("outlook=error")
    assert invalid.headers["location"].endswith("outlook=error")
    assert len(microsoft.exchanges) == 1


def test_callback_rejects_expired_state(oauth_setup) -> None:
    client, microsoft, database_path = oauth_setup
    state, _ = _start(client)
    with sqlite3.connect(database_path) as connection:
        connection.execute("UPDATE oauth_transactions SET expires_at = 0")

    response = client.get(
        "/api/v1/integrations/outlook/callback", params={"code": "auth-code", "state": state}
    )

    assert response.headers["location"].endswith("outlook=error")
    assert microsoft.exchanges == []


def test_microsoft_error_consumes_state(oauth_setup) -> None:
    client, microsoft, _ = oauth_setup
    state, _ = _start(client)

    denied = client.get(
        "/api/v1/integrations/outlook/callback",
        params={"error": "access_denied", "state": state},
    )
    replay = client.get(
        "/api/v1/integrations/outlook/callback",
        params={"code": "auth-code", "state": state},
    )

    assert denied.headers["location"].endswith("outlook=error")
    assert replay.headers["location"].endswith("outlook=error")
    assert microsoft.exchanges == []


def test_status_and_disconnect_require_owner_cookie_and_frontend_origin(oauth_setup) -> None:
    client, _, _ = oauth_setup
    assert client.get("/api/v1/integrations/outlook/status").status_code == 401
    assert client.post("/api/v1/integrations/outlook/disconnect").status_code == 401

    _start(client)
    assert client.post("/api/v1/integrations/outlook/disconnect").status_code == 403


def test_another_browser_cannot_access_replace_or_disconnect_connection(oauth_setup) -> None:
    owner, _, _ = oauth_setup
    state, _ = _start(owner)
    owner.get(
        "/api/v1/integrations/outlook/callback",
        params={"code": "auth-code", "state": state},
    )

    with TestClient(app, follow_redirects=False) as intruder:
        intruder.cookies.set(
            "pobridge_integration_session",
            "unrelated-high-entropy-session-value-12345",
            path="/api/v1/integrations/outlook",
        )
        assert intruder.get("/api/v1/integrations/outlook/status").status_code == 403
        assert intruder.get("/api/v1/integrations/outlook/connect").status_code == 403
        assert intruder.post(
            "/api/v1/integrations/outlook/disconnect",
            headers={"Origin": "http://localhost:3000"},
        ).status_code == 403
