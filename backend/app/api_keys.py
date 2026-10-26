import hashlib
import secrets


def create_api_key() -> tuple[str, str, str]:
    """Return (raw key, display prefix, SHA-256 hash); persist only prefix and hash."""
    raw_key = f"urumi_{secrets.token_urlsafe(32)}"
    key_prefix = raw_key[:14]
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return raw_key, key_prefix, key_hash


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
