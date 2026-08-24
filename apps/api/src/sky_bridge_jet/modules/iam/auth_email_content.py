"""Pure builders for the Phase 9.2.B1 verification email.

No template framework: two small deterministic functions render the plain-text and HTML
bodies. Content is factual and self-contained — Sky Bridge Jet identity, one verification
action, an expiry statement matching the 24-hour token TTL, and an "ignore if you did not
register" line. No marketing, tracking pixel, external analytics, remote image, password,
or internal identifier. The raw token appears only inside the verification URL fragment.
"""

from __future__ import annotations

from html import escape

from sky_bridge_jet.core.auth_email import VerificationEmail

VERIFICATION_SUBJECT = "Verify your Sky Bridge Jet email"


def build_verification_url(web_public_origin: str, raw_token: str) -> str:
    """Compose the fragment-form verification URL: ``<origin>/verify-email#token=<token>``.

    The origin is already validated/normalized by settings (scheme + host + optional
    port, no path/query/fragment/credentials). The token is URL-safe (``token_urlsafe``),
    so it is placed in the fragment verbatim. This full URL must never be logged.
    """
    return f"{web_public_origin.rstrip('/')}/verify-email#token={raw_token}"


def build_verification_email(
    *,
    recipient: str,
    verification_url: str,
    expires_in_hours: int,
) -> VerificationEmail:
    """Render the verification message for a recipient. Pure and side-effect free."""
    text_body = (
        "Sky Bridge Jet\n\n"
        "Confirm your email address to finish setting up your Sky Bridge Jet account.\n\n"
        "Verify your email:\n"
        f"{verification_url}\n\n"
        f"This link expires in {expires_in_hours} hours.\n\n"
        "If you did not create a Sky Bridge Jet account, you can safely ignore this "
        "email — no account will be activated.\n"
    )
    safe_url = escape(verification_url, quote=True)
    html_body = (
        "<!doctype html>"
        '<html lang="en"><body style="font-family:Arial,Helvetica,sans-serif;'
        'color:#0b2030;line-height:1.5">'
        '<h1 style="font-size:18px;margin:0 0 12px">Sky Bridge Jet</h1>'
        "<p>Confirm your email address to finish setting up your Sky Bridge Jet "
        "account.</p>"
        f'<p><a href="{safe_url}" style="color:#0b2030;font-weight:bold">'
        "Verify your email</a></p>"
        f"<p>This link expires in {expires_in_hours} hours.</p>"
        "<p>If you did not create a Sky Bridge Jet account, you can safely ignore this "
        "email — no account will be activated.</p>"
        "</body></html>"
    )
    return VerificationEmail(
        to=recipient,
        subject=VERIFICATION_SUBJECT,
        text_body=text_body,
        html_body=html_body,
    )
