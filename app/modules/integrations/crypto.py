"""Authenticated encryption for locally persisted integration secrets."""

from cryptography.fernet import Fernet, InvalidToken


class SecretCipher:
    """Encrypt and authenticate values before they reach persistent storage."""

    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise ValueError("INTEGRATION_ENCRYPTION_KEY must be a valid Fernet key") from exc

    def encrypt(self, value: str) -> bytes:
        return self._fernet.encrypt(value.encode("utf-8"))

    def decrypt(self, value: bytes) -> str:
        try:
            return self._fernet.decrypt(value).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise ValueError("Stored integration secret could not be decrypted") from exc
