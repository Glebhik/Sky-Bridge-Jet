"""LOCAL-ONLY manual smoke test for real Resend delivery (Phase 9.2.B1).

This is NOT a pytest test and never runs in CI. It sends ONE real verification email
using the configured Resend adapter, so it CONSUMES RESEND QUOTA. Run it manually only.

Usage (from apps/api):

    SMOKE_SEND=1 AUTH_EMAIL_ENABLED=true \
        uv run python scripts/auth_email_smoke.py you@example.com

It reads all provider configuration from Settings (the git-ignored .env / environment).
It NEVER prints the API key. Delivery uses a throwaway, clearly fake verification token
(no account is created or verified — this only exercises the transport).
"""

from __future__ import annotations

import os
import sys

from sky_bridge_jet.core.auth_email import build_auth_email_sender
from sky_bridge_jet.core.config import get_settings
from sky_bridge_jet.modules.iam.auth_email_content import (
    build_verification_email,
    build_verification_url,
)

_OPT_IN_ENV = "SMOKE_SEND"
_SMOKE_TOKEN = "SMOKE-not-a-real-token-do-not-use"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            "usage: SMOKE_SEND=1 AUTH_EMAIL_ENABLED=true "
            "python scripts/auth_email_smoke.py <recipient>"
        )
        return 2

    if os.getenv(_OPT_IN_ENV) != "1":
        print(
            f"Refusing to send: set {_OPT_IN_ENV}=1 to explicitly opt in "
            "(this consumes Resend quota)."
        )
        return 1

    recipient = argv[1]
    settings = get_settings()
    if not settings.auth_email_enabled:
        print("AUTH_EMAIL_ENABLED is not set; nothing to do.")
        return 1

    sender = build_auth_email_sender(settings)
    message = build_verification_email(
        recipient=recipient,
        verification_url=build_verification_url(settings.web_public_origin, _SMOKE_TOKEN),
        expires_in_hours=settings.email_verification_ttl_seconds // 3600,
    )
    print(f"Sending a real verification email to {recipient} (this consumes Resend quota)...")
    sender.send_verification_email(message)
    print("Sent. Check the recipient inbox. (No account was created or verified.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
