"""Microsoft identity platform and Graph client."""

from typing import Any, Protocol

import httpx


class MicrosoftOAuthClient(Protocol):
    async def exchange_code(self, *, code: str, code_verifier: str) -> dict[str, Any]: ...

    async def get_account(self, access_token: str) -> dict[str, Any]: ...


class HTTPMicrosoftOAuthClient:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        authority: str,
        redirect_uri: str,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._authority = authority.rstrip("/")
        self._redirect_uri = redirect_uri

    async def exchange_code(self, *, code: str, code_verifier: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{self._authority}/oauth2/v2.0/token",
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self._redirect_uri,
                    "code_verifier": code_verifier,
                },
            )
            response.raise_for_status()
            return response.json()

    async def get_account(self, access_token: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                "https://graph.microsoft.com/v1.0/me",
                params={"$select": "id,displayName,mail,userPrincipalName"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            return response.json()
