import re
import uuid

CORRELATION_ID_HEADER = "X-Request-ID"

# Correlation IDs are echoed into structured logs and response headers, so the
# accepted alphabet is deliberately narrow: unreserved URL characters only. This
# excludes "@", ":", whitespace, and other separators, which keeps out emails,
# bearer tokens, and similar PII/credential-shaped values a client might send.
MAX_CORRELATION_ID_LENGTH = 64
_SAFE_CORRELATION_ID = re.compile(r"[A-Za-z0-9._-]+")


def generate_correlation_id() -> str:
    """Return a fresh server-side correlation ID that is always log-safe."""
    return str(uuid.uuid4())


def sanitize_correlation_id(raw: str | None) -> str:
    """Return the client value only when it is short and matches the safe alphabet.

    Any absent, oversized, or otherwise unsafe value is replaced with a
    server-generated ID so that untrusted header content never reaches logs or
    response headers verbatim while legitimate request tracing is preserved.
    """
    if raw is None:
        return generate_correlation_id()
    if len(raw) > MAX_CORRELATION_ID_LENGTH:
        return generate_correlation_id()
    if _SAFE_CORRELATION_ID.fullmatch(raw) is None:
        return generate_correlation_id()
    return raw
