"""Encrypt upstream credentials at rest with a Fernet key supplied by deployment secrets."""

import json
import os

from cryptography.fernet import Fernet, InvalidToken


def _fernet():
    key = os.getenv("APP_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("APP_ENCRYPTION_KEY is required to store upstream credentials")
    return Fernet(key.encode())


def encrypt_credentials(value: dict) -> str:
    return _fernet().encrypt(json.dumps(value).encode()).decode()


def decrypt_credentials(value: str | None) -> dict:
    if not value:
        return {}
    try:
        return json.loads(_fernet().decrypt(value.encode()).decode())
    except (InvalidToken, ValueError):
        raise RuntimeError("Upstream credential decryption failed") from None
