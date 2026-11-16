"""HTTP routes for the local single-user Outlook integration."""

import secrets
from functools import lru_cache
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.core.config import settings
from app.modules.integrations.crypto import SecretCipher
from app.modules.integrations.microsoft import HTTPMicrosoftOAuthClient
from app.modules.integrations.outlook import (
    ConnectionOwnedByAnotherSession,
    OAuthCallbackError,
    OutlookIntegrationService,
)
from app.modules.integrations.repository import SQLiteIntegrationRepository

router = APIRouter(prefix="/integrations/outlook", tags=["integrations"])
SESSION_COOKIE = "pobridge_integration_session"


class OutlookStatusResponse(BaseModel):
    connected: bool
    email: str | None = None


def _configured_service() -> OutlookIntegrationService:
    missing = [
        name
        for name, value in (
            ("MICROSOFT_CLIENT_ID", settings.MICROSOFT_CLIENT_ID),
            ("MICROSOFT_CLIENT_SECRET", settings.MICROSOFT_CLIENT_SECRET),
            ("INTEGRATION_ENCRYPTION_KEY", settings.INTEGRATION_ENCRYPTION_KEY),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing Outlook integration configuration: {', '.join(missing)}")
    if not settings.MICROSOFT_AUTHORITY.rstrip("/").endswith("/common"):
        raise RuntimeError("MICROSOFT_AUTHORITY must use the Microsoft common authority")
    cipher = SecretCipher(settings.INTEGRATION_ENCRYPTION_KEY or "")
    return OutlookIntegrationService(
        repository=SQLiteIntegrationRepository(settings.INTEGRATION_DATABASE_PATH),
        cipher=cipher,
        microsoft=HTTPMicrosoftOAuthClient(
            client_id=settings.MICROSOFT_CLIENT_ID or "",
            client_secret=settings.MICROSOFT_CLIENT_SECRET or "",
            authority=settings.MICROSOFT_AUTHORITY,
            redirect_uri=str(settings.MICROSOFT_REDIRECT_URI),
        ),
        client_id=settings.MICROSOFT_CLIENT_ID or "",
        authority=settings.MICROSOFT_AUTHORITY,
        redirect_uri=str(settings.MICROSOFT_REDIRECT_URI),
        transaction_ttl_seconds=settings.OAUTH_TRANSACTION_TTL_SECONDS,
    )


@lru_cache
def get_outlook_service() -> OutlookIntegrationService:
    try:
        return _configured_service()
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc


def require_service() -> OutlookIntegrationService:
    try:
        return get_outlook_service()
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


def require_session(
    session_id: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> str:
    if not session_id or len(session_id) < 32:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Integration session required")
    return session_id


def _frontend_redirect(result: str) -> RedirectResponse:
    base = str(settings.FRONTEND_URL).rstrip("/") + "/integrations/outlook"
    return RedirectResponse(f"{base}?{urlencode({'outlook': result})}", status_code=303)


@router.get("/connect", status_code=307)
def connect(
    session_id: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    service: OutlookIntegrationService = Depends(require_service),
) -> RedirectResponse:
    session_id = session_id if session_id and len(session_id) >= 32 else secrets.token_urlsafe(32)
    try:
        authorization_url = service.start_authorization(session_id)
    except ConnectionOwnedByAnotherSession as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Connection belongs to another local session") from exc
    response = RedirectResponse(authorization_url, status_code=307)
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=60 * 60 * 24 * 30,
        httponly=True,
        secure=settings.INTEGRATION_COOKIE_SECURE,
        samesite="lax",
        path=f"{settings.API_V1_PREFIX}/integrations/outlook",
    )
    return response


@router.get("/callback")
async def callback(
    code: str | None = Query(default=None),
    state_value: str | None = Query(default=None, alias="state"),
    error: str | None = Query(default=None),
    session_id: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    service: OutlookIntegrationService = Depends(require_service),
) -> RedirectResponse:
    if not state_value or not session_id:
        return _frontend_redirect("error")
    if error:
        try:
            service.reject_authorization(state=state_value, session_id=session_id)
        except OAuthCallbackError:
            pass
        return _frontend_redirect("error")
    if not code:
        try:
            service.reject_authorization(state=state_value, session_id=session_id)
        except OAuthCallbackError:
            pass
        return _frontend_redirect("error")
    try:
        await service.complete_authorization(code=code, state=state_value, session_id=session_id)
    except (OAuthCallbackError, httpx.HTTPError):
        return _frontend_redirect("error")
    return _frontend_redirect("success")


@router.get("/status", response_model=OutlookStatusResponse)
def connection_status(
    session_id: str = Depends(require_session),
    service: OutlookIntegrationService = Depends(require_service),
) -> OutlookStatusResponse:
    try:
        current = service.status(session_id)
    except ConnectionOwnedByAnotherSession as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Connection belongs to another local session") from exc
    return OutlookStatusResponse(connected=current.connected, email=current.email)


@router.post("/disconnect", response_model=OutlookStatusResponse)
def disconnect(
    request: Request,
    response: Response,
    session_id: str = Depends(require_session),
    service: OutlookIntegrationService = Depends(require_service),
) -> OutlookStatusResponse:
    expected_origin = str(settings.FRONTEND_URL).rstrip("/")
    if request.headers.get("origin") != expected_origin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid request origin")
    try:
        service.disconnect(session_id)
    except ConnectionOwnedByAnotherSession as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Connection belongs to another local session") from exc
    response.delete_cookie(
        SESSION_COOKIE,
        path=f"{settings.API_V1_PREFIX}/integrations/outlook",
        secure=settings.INTEGRATION_COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )
    return OutlookStatusResponse(connected=False)
