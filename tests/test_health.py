"""Tests for application initialization and health checks."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_application_initializes() -> None:
    assert app.title == "POBridge API"
    assert app.version == "0.1.0"


def test_health_check() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "application": "POBridge API",
        "version": "0.1.0",
    }


def test_api_documentation_is_available() -> None:
    response = client.get("/docs")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_cors_allows_configured_frontend_origin() -> None:
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers["access-control-allow-credentials"] == "true"
