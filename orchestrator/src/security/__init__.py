"""Hash API key secrets for lookup (never store plaintext)."""

from __future__ import annotations

import hashlib


def hash_api_key(secret: str, pepper: str) -> str:
    """Deterministic SHA-256 hex digest of pepper and secret."""
    payload = f"{pepper}\x00{secret}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def key_prefix(secret: str, max_len: int = 16) -> str:
    if len(secret) <= max_len:
        return secret
    return secret[:max_len]
