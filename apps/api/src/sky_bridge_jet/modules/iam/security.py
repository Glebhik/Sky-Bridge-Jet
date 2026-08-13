"""Password and token primitives. We never implement crypto ourselves.

- Passwords: Argon2id via ``argon2-cffi`` (hash, constant-time verify, rehash).
- Tokens (session/verification/reset/invitation): a high-entropy opaque secret is
  generated and returned once; only its SHA-256 hash is persisted, so a database
  disclosure never yields a reusable secret.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

# Library-managed Argon2id parameters. Tuning is the library's concern, not ours.
_hasher = PasswordHasher()

# Opaque token entropy (bytes) before URL-safe encoding.
_TOKEN_BYTES = 32


def hash_password(password: str) -> str:
    """Return an Argon2id PHC-string hash. The plaintext is never logged."""
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    """Constant-time verification via the library. Never a naive ``==`` compare."""
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def password_needs_rehash(stored_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return True


def generate_token() -> str:
    """Generate a high-entropy, URL-safe opaque secret (returned to the client once)."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(token: str) -> str:
    """Deterministic SHA-256 of a token for at-rest storage and lookup.

    Tokens are already high-entropy, so a fast hash is appropriate (unlike
    passwords) and lets us index the digest for O(1) lookup.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_equal(candidate_hash: str, stored_hash: str) -> bool:
    """Constant-time comparison of two token digests."""
    return hmac.compare_digest(candidate_hash, stored_hash)
