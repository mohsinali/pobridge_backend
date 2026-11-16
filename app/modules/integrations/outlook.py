"""Outlook OAuth application service."""

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from app.modules.integrations.crypto import SecretCipher
from app.modules.integrations.microsoft import MicrosoftOAuthClient
from app.modules.integrations.repository import (
    IntegrationConnection,
    IntegrationRepository,
    OAuthTransaction,
)

PROVIDER = "outlook"
SCOPES = ("openid", "profile", "email", "User.Read", "Mail.Read", "offline_access")


class OAuthCallbackError(Exception):
    """A safe, expected OAuth callback failure."""


class ConnectionOwnedByAnotherSession(Exception):
    """The local single-user connection is bound to another browser session."""


@dataclass(frozen=True)
class ConnectionStatus:
    connected: bool
    email: str | None = None


class OutlookIntegrationService:
    def __init__(
        self,
        *,
        repository: IntegrationRepository,
        cipher: SecretCipher,
        microsoft: MicrosoftOAuthClient,
        client_id: str,
        authority: str,
        redirect_uri: str,
        transaction_ttl_seconds: int,
    ) -> None:
        self._repository = repository
        self._cipher = cipher
        self._microsoft = microsoft
        self._client_id = client_id
        self._authority = authority.rstrip("/")
        self._redirect_uri = redirect_uri
        self._transaction_ttl_seconds = transaction_ttl_seconds

    @staticmethod
    def hash_secret(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def start_authorization(self, session_id: str) -> str:
        session_hash = self.hash_secret(session_id)
        connection = self._repository.get_connection(PROVIDER)
        if connection is not None and connection.owner_session_hash != session_hash:
            raise ConnectionOwnedByAnotherSession

        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        self._repository.create_oauth_transaction(
            state_hash=self.hash_secret(state),
            provider=PROVIDER,
            session_hash=session_hash,
            encrypted_verifier=self._cipher.encrypt(verifier),
            expires_at=int(time.time()) + self._transaction_ttl_seconds,
        )
        query = urlencode(
            {
                "client_id": self._client_id,
                "response_type": "code",
                "redirect_uri": self._redirect_uri,
                "response_mode": "query",
                "scope": " ".join(SCOPES),
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{self._authority}/oauth2/v2.0/authorize?{query}"

    async def complete_authorization(self, *, code: str, state: str, session_id: str) -> str:
        transaction = self._consume_transaction(state=state, session_id=session_id)

        try:
            verifier = self._cipher.decrypt(transaction.encrypted_verifier)
            tokens = await self._microsoft.exchange_code(code=code, code_verifier=verifier)
            access_token = tokens.get("access_token")
            refresh_token = tokens.get("refresh_token")
            if not isinstance(access_token, str) or not isinstance(refresh_token, str):
                raise OAuthCallbackError("Microsoft did not return the required credentials")
            account = await self._microsoft.get_account(access_token)
            account_id = account.get("id")
            email = account.get("mail") or account.get("userPrincipalName")
            display_name = account.get("displayName")
            if not isinstance(account_id, str) or not isinstance(email, str):
                raise OAuthCallbackError("Microsoft account details were incomplete")

            credentials: dict[str, Any] = {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": tokens.get("token_type"),
                "scope": tokens.get("scope"),
                "expires_in": tokens.get("expires_in"),
                "obtained_at": int(time.time()),
            }
            saved = self._repository.save_connection(
                IntegrationConnection(
                    provider=PROVIDER,
                    owner_session_hash=self.hash_secret(session_id),
                    account_id=account_id,
                    email=email,
                    display_name=display_name if isinstance(display_name, str) else None,
                    encrypted_credentials=self._cipher.encrypt(
                        json.dumps(credentials, separators=(",", ":"))
                    ),
                )
            )
            if not saved:
                raise OAuthCallbackError("The connection is owned by another local session")
            return email
        except OAuthCallbackError:
            raise
        except Exception as exc:
            raise OAuthCallbackError("Microsoft OAuth completion failed") from exc

    def reject_authorization(self, *, state: str, session_id: str) -> None:
        """Validate and consume a transaction when Microsoft returns an OAuth error."""
        self._consume_transaction(state=state, session_id=session_id)

    def _consume_transaction(self, *, state: str, session_id: str) -> OAuthTransaction:
        session_hash = self.hash_secret(session_id)
        transaction = self._repository.consume_oauth_transaction(
            state_hash=self.hash_secret(state),
            provider=PROVIDER,
            session_hash=session_hash,
            now=int(time.time()),
        )
        if transaction is None:
            raise OAuthCallbackError("Invalid, expired, or already-used OAuth state")
        return transaction

    def status(self, session_id: str) -> ConnectionStatus:
        connection = self._repository.get_connection(PROVIDER)
        if connection is None:
            return ConnectionStatus(connected=False)
        if connection.owner_session_hash != self.hash_secret(session_id):
            raise ConnectionOwnedByAnotherSession
        return ConnectionStatus(connected=True, email=connection.email)

    def disconnect(self, session_id: str) -> bool:
        connection = self._repository.get_connection(PROVIDER)
        if connection is None:
            return False
        if connection.owner_session_hash != self.hash_secret(session_id):
            raise ConnectionOwnedByAnotherSession
        return self._repository.delete_connection(
            provider=PROVIDER, owner_session_hash=connection.owner_session_hash
        )
