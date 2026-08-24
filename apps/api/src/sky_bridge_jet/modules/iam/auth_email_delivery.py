"""Post-commit verification-email delivery for the auth routes (Phase 9.2.B1).

This is invoked by the register / verification-resend route handlers **after** the IAM
transaction has already committed, so a provider network call never runs inside a
``session.begin()`` block or while a ``FOR UPDATE`` lock is held.

Delivery failure policy (owner-approved): a durable account/token operation is never
rolled back because the email provider is unavailable. A failure is swallowed and recorded
as a safe, non-sensitive structured log — never the recipient, token, verification URL,
Authorization header, or API key. The route therefore keeps its normal contract, and the
verification-resend acknowledgement stays enumeration-safe regardless of provider outcome.
"""

from __future__ import annotations

import logging

from sky_bridge_jet.core.auth_email import AuthEmailError, AuthEmailSender
from sky_bridge_jet.core.config import Settings
from sky_bridge_jet.modules.iam.auth_email_content import (
    build_verification_email,
    build_verification_url,
)

_logger = logging.getLogger(__name__)


def deliver_verification_email(
    sender: AuthEmailSender,
    settings: Settings,
    *,
    recipient: str,
    raw_token: str,
    operation: str,
) -> None:
    """Render and send the verification email; never raise.

    ``operation`` is a non-sensitive route label used only for the failure log.
    """
    message = build_verification_email(
        recipient=recipient,
        verification_url=build_verification_url(settings.web_public_origin, raw_token),
        expires_in_hours=settings.email_verification_ttl_seconds // 3600,
    )
    try:
        sender.send_verification_email(message)
    except AuthEmailError as error:
        # The account/token are already durable. Record only a safe category — the
        # JsonFormatter whitelists `operation`/`error_type`, so no recipient, token,
        # URL, header, or key can reach the log.
        _logger.warning(
            "auth_email_delivery_failed",
            extra={"operation": operation, "error_type": error.category.value},
        )
