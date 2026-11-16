"""SQLite persistence behind an interface replaceable by a production database."""

import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class OAuthTransaction:
    encrypted_verifier: bytes


@dataclass(frozen=True)
class IntegrationConnection:
    provider: str
    owner_session_hash: str
    account_id: str
    email: str
    display_name: str | None
    encrypted_credentials: bytes


class IntegrationRepository(Protocol):
    def create_oauth_transaction(
        self,
        *,
        state_hash: str,
        provider: str,
        session_hash: str,
        encrypted_verifier: bytes,
        expires_at: int,
    ) -> None: ...

    def consume_oauth_transaction(
        self, *, state_hash: str, provider: str, session_hash: str, now: int
    ) -> OAuthTransaction | None: ...

    def get_connection(self, provider: str) -> IntegrationConnection | None: ...

    def save_connection(self, connection: IntegrationConnection) -> bool: ...

    def delete_connection(self, *, provider: str, owner_session_hash: str) -> bool: ...


class SQLiteIntegrationRepository:
    """Small synchronous store for the single-user local development deployment."""

    def __init__(self, database_path: str) -> None:
        self._database_path = database_path
        Path(database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        os.chmod(database_path, 0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS oauth_transactions (
                    state_hash TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    session_hash TEXT NOT NULL,
                    encrypted_verifier BLOB NOT NULL,
                    expires_at INTEGER NOT NULL,
                    consumed_at INTEGER
                );
                CREATE TABLE IF NOT EXISTS integration_connections (
                    provider TEXT PRIMARY KEY,
                    owner_session_hash TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    email TEXT NOT NULL,
                    display_name TEXT,
                    encrypted_credentials BLOB NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                """
            )

    def create_oauth_transaction(
        self,
        *,
        state_hash: str,
        provider: str,
        session_hash: str,
        encrypted_verifier: bytes,
        expires_at: int,
    ) -> None:
        now = int(time.time())
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM oauth_transactions WHERE expires_at < ? OR consumed_at IS NOT NULL",
                (now,),
            )
            connection.execute(
                """INSERT INTO oauth_transactions
                   (state_hash, provider, session_hash, encrypted_verifier, expires_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (state_hash, provider, session_hash, encrypted_verifier, expires_at),
            )

    def consume_oauth_transaction(
        self, *, state_hash: str, provider: str, session_hash: str, now: int
    ) -> OAuthTransaction | None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT encrypted_verifier FROM oauth_transactions
                   WHERE state_hash = ? AND provider = ? AND session_hash = ?
                     AND consumed_at IS NULL AND expires_at >= ?""",
                (state_hash, provider, session_hash, now),
            ).fetchone()
            if row is None:
                connection.rollback()
                return None
            updated = connection.execute(
                """UPDATE oauth_transactions SET consumed_at = ?
                   WHERE state_hash = ? AND consumed_at IS NULL""",
                (now, state_hash),
            )
            if updated.rowcount != 1:
                connection.rollback()
                return None
            connection.commit()
            return OAuthTransaction(encrypted_verifier=row["encrypted_verifier"])
        finally:
            connection.close()

    def get_connection(self, provider: str) -> IntegrationConnection | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM integration_connections WHERE provider = ?", (provider,)
            ).fetchone()
        if row is None:
            return None
        return IntegrationConnection(
            provider=row["provider"],
            owner_session_hash=row["owner_session_hash"],
            account_id=row["account_id"],
            email=row["email"],
            display_name=row["display_name"],
            encrypted_credentials=row["encrypted_credentials"],
        )

    def save_connection(self, connection: IntegrationConnection) -> bool:
        """Save only when unclaimed or owned by the same browser session."""
        now = int(time.time())
        database = self._connect()
        try:
            database.execute("BEGIN IMMEDIATE")
            owner = database.execute(
                "SELECT owner_session_hash FROM integration_connections WHERE provider = ?",
                (connection.provider,),
            ).fetchone()
            if owner is not None and owner["owner_session_hash"] != connection.owner_session_hash:
                database.rollback()
                return False
            database.execute(
                """INSERT INTO integration_connections
                   (provider, owner_session_hash, account_id, email, display_name,
                    encrypted_credentials, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(provider) DO UPDATE SET
                     account_id=excluded.account_id,
                     email=excluded.email,
                     display_name=excluded.display_name,
                     encrypted_credentials=excluded.encrypted_credentials,
                     updated_at=excluded.updated_at""",
                (
                    connection.provider,
                    connection.owner_session_hash,
                    connection.account_id,
                    connection.email,
                    connection.display_name,
                    connection.encrypted_credentials,
                    now,
                    now,
                ),
            )
            database.commit()
            return True
        finally:
            database.close()

    def delete_connection(self, *, provider: str, owner_session_hash: str) -> bool:
        with self._connect() as connection:
            result = connection.execute(
                "DELETE FROM integration_connections WHERE provider = ? AND owner_session_hash = ?",
                (provider, owner_session_hash),
            )
        return result.rowcount == 1
