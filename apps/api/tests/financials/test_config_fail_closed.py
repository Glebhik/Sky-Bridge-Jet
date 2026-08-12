"""Fail-closed enforcement of Stripe TEST MODE (no database required).

Phase 7 must *enforce*, not merely document, test-mode-only operation: a live
secret key must be rejected when test mode is required, and the key must never be
echoed in the error.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sky_bridge_jet.core.config import Settings


def test_stripe_disabled_boots_without_configuration() -> None:
    settings = Settings(stripe_enabled=False)
    assert settings.stripe_enabled is False
    assert settings.stripe_live_key_detected is False


def test_enabled_requires_secret_and_webhook() -> None:
    with pytest.raises(ValidationError) as secret_error:
        Settings(stripe_enabled=True, stripe_secret_key=None, stripe_webhook_secret="whsec_x")
    assert "STRIPE_SECRET_KEY is required" in str(secret_error.value)

    with pytest.raises(ValidationError) as webhook_error:
        Settings(stripe_enabled=True, stripe_secret_key="sk_test_x", stripe_webhook_secret=None)
    assert "STRIPE_WEBHOOK_SECRET is required" in str(webhook_error.value)


def test_live_secret_key_rejected_in_test_mode() -> None:
    live_key = "sk_live_super_secret_value_should_never_appear"
    with pytest.raises(ValidationError) as error:
        Settings(
            stripe_enabled=True,
            stripe_secret_key=live_key,
            stripe_webhook_secret="whsec_x",
            stripe_test_mode_required=True,
        )
    message = str(error.value)
    assert "live Stripe secret key is not permitted" in message
    # The secret value itself must never be echoed in the error.
    assert "super_secret_value_should_never_appear" not in message
    assert live_key not in message


def test_restricted_live_key_prefix_also_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(
            stripe_enabled=True,
            stripe_secret_key="rk_live_restricted",
            stripe_webhook_secret="whsec_x",
            stripe_test_mode_required=True,
        )


def test_test_mode_key_accepted() -> None:
    settings = Settings(
        stripe_enabled=True,
        stripe_secret_key="sk_test_ok",
        stripe_webhook_secret="whsec_ok",
    )
    assert settings.stripe_enabled is True
    assert settings.stripe_live_key_detected is False


def test_live_key_detected_property_true_for_live_key() -> None:
    # When test mode is not required the object constructs, but the live-key
    # detector still reports the risk so callers can fail closed elsewhere.
    settings = Settings(
        stripe_enabled=True,
        stripe_secret_key="sk_live_detect",
        stripe_webhook_secret="whsec_x",
        stripe_test_mode_required=False,
    )
    assert settings.stripe_live_key_detected is True
