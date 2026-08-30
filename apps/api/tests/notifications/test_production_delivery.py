from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import uuid4

import iam_support
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from sky_bridge_jet.core.config import Settings, get_settings
from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.notifications.delivery import (
    FakeMarketplaceNotificationSender,
    MarketplaceEmail,
    NotificationDeliveryError,
    ResendMarketplaceNotificationSender,
    build_marketplace_notification_sender,
)
from sky_bridge_jet.modules.notifications.domain import (
    NotificationDeliveryState,
    NotificationFailureCode,
    ProviderDeliveryState,
    provider_delivery_should_advance,
)
from sky_bridge_jet.modules.notifications.marketplace import (
    ClaimedNotification,
    MarketplaceNotificationDispatcher,
)
from sky_bridge_jet.modules.notifications.models import (
    NotificationOutbox,
    NotificationProviderEvent,
)
from sky_bridge_jet.modules.notifications.webhooks import _verify


class _Response:
    headers = {"x-request-id": "request-safe"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _limit: int) -> bytes:
        return b'{"id":"provider-message-1"}'


def _message() -> MarketplaceEmail:
    return MarketplaceEmail(
        recipient="pilot@example.test",
        subject="Trusted subject",
        text_body="Trusted body",
        idempotency_key="notification-id",
    )


def test_resend_acceptance_is_narrow_and_idempotent(monkeypatch) -> None:
    captured = {}

    def urlopen(request, *, timeout):
        captured.update(request=request, timeout=timeout)
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    result = ResendMarketplaceNotificationSender(
        "re_test_only", "Sky Bridge Jet <no-reply@example.test>", timeout_seconds=3
    ).send(_message())
    assert result.provider_message_id == "provider-message-1"
    request = captured["request"]
    assert request.full_url == "https://api.resend.com/emails"
    assert request.headers["Idempotency-key"] == "notification-id"
    assert json.loads(request.data) == {
        "from": "Sky Bridge Jet <no-reply@example.test>",
        "to": ["pilot@example.test"],
        "subject": "Trusted subject",
        "text": "Trusted body",
    }
    assert captured["timeout"] == 3


@pytest.mark.parametrize(
    ("status", "code", "retryable", "systemic"),
    [
        (401, NotificationFailureCode.PROVIDER_SYSTEMIC_AUTH, True, True),
        (403, NotificationFailureCode.PROVIDER_SYSTEMIC_AUTH, True, True),
        (429, NotificationFailureCode.PROVIDER_RATE_LIMIT, True, True),
        (500, NotificationFailureCode.TRANSIENT_PROVIDER, True, True),
        (422, NotificationFailureCode.INVALID_RECIPIENT, False, False),
    ],
)
def test_resend_error_normalization(monkeypatch, status, code, retryable, systemic) -> None:
    def urlopen(*_args, **_kwargs):
        body = b'{"name":"invalid_recipient"}' if status == 422 else b"{}"
        raise urllib.error.HTTPError(
            "https://api.resend.com/emails", status, "x", {}, BytesIO(body)
        )

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    with pytest.raises(NotificationDeliveryError) as raised:
        ResendMarketplaceNotificationSender(
            "re_test_only", "from@example.test", timeout_seconds=3
        ).send(_message())
    assert (raised.value.code, raised.value.retryable, raised.value.systemic) == (
        code,
        retryable,
        systemic,
    )


@pytest.mark.parametrize(
    ("body", "expected_code"),
    [
        (b'{"name":"concurrent_idempotent_requests"}', NotificationFailureCode.TRANSIENT_PROVIDER),
        (
            b'{"name":"invalid_idempotent_request"}',
            NotificationFailureCode.PROVIDER_SYSTEMIC_POLICY,
        ),
        (b"not-json", NotificationFailureCode.PROVIDER_SYSTEMIC_POLICY),
        (b'{"message":"missing code"}', NotificationFailureCode.PROVIDER_SYSTEMIC_POLICY),
    ],
)
def test_resend_409_is_never_recipient_failure(monkeypatch, body, expected_code) -> None:
    def urlopen(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "https://api.resend.com/emails", 409, "conflict", {}, BytesIO(body)
        )

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    with pytest.raises(NotificationDeliveryError) as raised:
        ResendMarketplaceNotificationSender(
            "re_test_only", "from@example.test", timeout_seconds=3
        ).send(_message())
    assert raised.value.code is expected_code
    assert raised.value.retryable
    assert raised.value.systemic


def test_resend_error_response_is_bounded(monkeypatch) -> None:
    def urlopen(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "https://api.resend.com/emails", 409, "conflict", {}, BytesIO(b"x" * 8193)
        )

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    with pytest.raises(NotificationDeliveryError) as raised:
        ResendMarketplaceNotificationSender(
            "re_test_only", "from@example.test", timeout_seconds=3
        ).send(_message())
    assert raised.value.code is NotificationFailureCode.PROVIDER_SYSTEMIC_POLICY
    assert raised.value.systemic


@pytest.mark.parametrize("provider_error", ["validation_error", "invalid_from_address"])
def test_ambiguous_validation_error_does_not_burn_recipient(
    monkeypatch, provider_error: str
) -> None:
    def urlopen(*_args, **_kwargs):
        body = json.dumps({"name": provider_error}).encode()
        raise urllib.error.HTTPError(
            "https://api.resend.com/emails", 422, "invalid", {}, BytesIO(body)
        )

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    with pytest.raises(NotificationDeliveryError) as raised:
        ResendMarketplaceNotificationSender(
            "re_test_only", "from@example.test", timeout_seconds=3
        ).send(_message())
    assert raised.value.code is NotificationFailureCode.PROVIDER_SYSTEMIC_POLICY
    assert raised.value.retryable
    assert raised.value.systemic


def test_concurrent_idempotent_response_retries_same_provider_key(monkeypatch) -> None:
    captured_keys: list[str] = []

    def urlopen(request, *, timeout):
        del timeout
        captured_keys.append(request.headers["Idempotency-key"])
        if len(captured_keys) == 1:
            raise urllib.error.HTTPError(
                "https://api.resend.com/emails",
                409,
                "conflict",
                {},
                BytesIO(b'{"name":"concurrent_idempotent_requests"}'),
            )
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    sender = ResendMarketplaceNotificationSender(
        "re_test_only", "from@example.test", timeout_seconds=3
    )
    with pytest.raises(NotificationDeliveryError) as first:
        sender.send(_message())
    assert first.value.code is NotificationFailureCode.TRANSIENT_PROVIDER
    assert sender.send(_message()).provider_message_id == "provider-message-1"
    assert captured_keys == ["notification-id", "notification-id"]


def test_sender_factory_keeps_disabled_and_fake_modes_distinct() -> None:
    with pytest.raises(ValueError, match="delivery is disabled"):
        build_marketplace_notification_sender(Settings())
    sender = build_marketplace_notification_sender(
        Settings(
            app_environment="test",
            marketplace_email_enabled=True,
            marketplace_email_provider="fake",
        )
    )
    assert isinstance(sender, FakeMarketplaceNotificationSender)


@pytest.mark.parametrize(
    ("current", "current_minute", "candidate", "candidate_minute", "expected"),
    [
        (ProviderDeliveryState.DELIVERED, 3, ProviderDeliveryState.DELIVERY_DELAYED, 2, False),
        (ProviderDeliveryState.DELIVERY_DELAYED, 2, ProviderDeliveryState.ACCEPTED, 1, False),
        (ProviderDeliveryState.DELIVERED, 3, ProviderDeliveryState.COMPLAINED, 4, True),
        (ProviderDeliveryState.COMPLAINED, 4, ProviderDeliveryState.DELIVERED, 3, False),
        (ProviderDeliveryState.DELIVERED, 3, ProviderDeliveryState.BOUNCED, 4, True),
        (ProviderDeliveryState.BOUNCED, 4, ProviderDeliveryState.SUPPRESSED, 4, True),
        (ProviderDeliveryState.SUPPRESSED, 4, ProviderDeliveryState.COMPLAINED, 4, True),
        (ProviderDeliveryState.COMPLAINED, 4, ProviderDeliveryState.SUPPRESSED, 4, False),
        (ProviderDeliveryState.DELIVERED, 3, ProviderDeliveryState.DELIVERED, 3, False),
    ],
)
def test_provider_event_temporal_and_equal_time_precedence_matrix(
    current: ProviderDeliveryState,
    current_minute: int,
    candidate: ProviderDeliveryState,
    candidate_minute: int,
    expected: bool,
) -> None:
    origin = datetime(2026, 8, 29, tzinfo=UTC)
    assert (
        provider_delivery_should_advance(
            current_state=current.value,
            current_occurred_at=origin + timedelta(minutes=current_minute),
            candidate_state=candidate,
            candidate_occurred_at=origin + timedelta(minutes=candidate_minute),
        )
        is expected
    )


def test_marketplace_email_config_fails_closed() -> None:
    with pytest.raises(ValueError, match="approved recipient allowlist"):
        Settings(
            app_environment="staging",
            privileged_identity_provider="auth0",
            auth0_issuer="https://identity.example.test",
            auth0_client_id="client",
            auth0_callback_url="https://web.example.test/callback",
            auth0_environment_id="staging",
            marketplace_email_enabled=True,
            marketplace_email_provider="resend",
            resend_api_key="re_test",
            resend_webhook_secret="whsec_dGVzdA==",
        )


def _signature(secret: str, event_id: str, timestamp: str, body: bytes) -> str:
    key = base64.b64decode(secret.removeprefix("whsec_"))
    signed = event_id.encode() + b"." + timestamp.encode() + b"." + body
    return "v1," + base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()


def _post_webhook(
    client,
    *,
    secret: str,
    event_id: str,
    event_type: str,
    message_id: str,
    occurred_at: datetime,
):
    timestamp = str(int(datetime.now(UTC).timestamp()))
    body = json.dumps(
        {
            "type": event_type,
            "created_at": occurred_at.isoformat(),
            "data": {"email_id": message_id},
        },
        separators=(",", ":"),
    ).encode()
    return client.post(
        "/api/v1/webhooks/resend",
        content=body,
        headers={
            "content-type": "application/json",
            "svix-id": event_id,
            "svix-timestamp": timestamp,
            "svix-signature": _signature(secret, event_id, timestamp, body),
        },
    )


def test_webhook_signature_matrix() -> None:
    secret = "whsec_" + base64.b64encode(b"test-secret").decode()
    event_id = "event-1"
    timestamp = str(int(datetime.now(UTC).timestamp()))
    body = b'{"type":"email.delivered"}'
    _verify(secret, event_id, timestamp, _signature(secret, event_id, timestamp, body), body)
    with pytest.raises(HTTPException):
        _verify(secret, event_id, timestamp, "v1,invalid", body)
    with pytest.raises(HTTPException):
        _verify(secret, event_id, str(int(timestamp) - 301), "v1,invalid", body)


@pytest.mark.integration
def test_signed_prelink_events_reconcile_by_latest_provider_time(monkeypatch) -> None:
    secret = "whsec_" + base64.b64encode(b"prelink-secret").decode()
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", secret)
    get_settings.cache_clear()
    client = iam_support.new_client()
    user_id = iam_support.register_verify_login(client)
    notification_id = uuid4()
    claim_token = uuid4()
    provider_message_id = f"prelink-{notification_id}"
    now = datetime.now(UTC)
    with SessionLocal.begin() as session:
        session.add(
            NotificationOutbox(
                id=notification_id,
                dedupe_key=f"signed-prelink:{notification_id}",
                event_type="OFFER_AVAILABLE",
                recipient_user_id=user_id,
                resource_type="OFFER",
                resource_id=uuid4(),
                delivery_state=NotificationDeliveryState.CLAIMED,
                attempt_count=1,
                claim_token=claim_token,
                claimed_at=now,
            )
        )
    events = [
        ("email.complained", now - timedelta(minutes=1)),
        ("email.sent", now - timedelta(minutes=4)),
        ("email.delivered", now - timedelta(minutes=2)),
        ("email.delivery_delayed", now - timedelta(minutes=3)),
    ]
    for index, (event_type, occurred_at) in enumerate(events):
        assert (
            _post_webhook(
                client,
                secret=secret,
                event_id=f"prelink-{notification_id}-{index}",
                event_type=event_type,
                message_id=provider_message_id,
                occurred_at=occurred_at,
            ).status_code
            == 204
        )
    with SessionLocal() as session:
        dispatcher = MarketplaceNotificationDispatcher(
            session, FakeMarketplaceNotificationSender(), Settings()
        )
        assert dispatcher._mark_delivered(
            ClaimedNotification(
                id=notification_id,
                claim_token=claim_token,
                event=None,
                recipient_user_id=user_id,
                resource_type="OFFER",
                resource_id=uuid4(),
                attempt_count=1,
            ),
            now,
            provider_message_id,
        )
    with SessionLocal() as session:
        row = session.get_one(NotificationOutbox, notification_id)
        assert row.provider_delivery_state == "COMPLAINED"
        assert row.provider_event_at == now - timedelta(minutes=1)
    client.close()
    get_settings.cache_clear()


@pytest.mark.integration
def test_concurrent_webhooks_converge_on_newest_provider_time(monkeypatch) -> None:
    secret = "whsec_" + base64.b64encode(b"concurrent-secret").decode()
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", secret)
    get_settings.cache_clear()
    setup_client = iam_support.new_client()
    user_id = iam_support.register_verify_login(setup_client)
    notification_id = uuid4()
    provider_message_id = f"concurrent-{notification_id}"
    now = datetime.now(UTC)
    with SessionLocal.begin() as session:
        session.add(
            NotificationOutbox(
                id=notification_id,
                dedupe_key=f"concurrent:{notification_id}",
                event_type="OFFER_AVAILABLE",
                recipient_user_id=user_id,
                resource_type="OFFER",
                resource_id=uuid4(),
                delivery_state=NotificationDeliveryState.DELIVERED,
                provider_message_id=provider_message_id,
                provider_delivery_state="ACCEPTED",
            )
        )
    barrier = threading.Barrier(2)

    def ingest(event_id: str, event_type: str, occurred_at: datetime) -> int:
        with iam_support.new_client() as client:
            barrier.wait()
            return _post_webhook(
                client,
                secret=secret,
                event_id=event_id,
                event_type=event_type,
                message_id=provider_message_id,
                occurred_at=occurred_at,
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda args: ingest(*args),
                [
                    (f"older-{notification_id}", "email.complained", now - timedelta(minutes=2)),
                    (f"newer-{notification_id}", "email.delivered", now - timedelta(minutes=1)),
                ],
            )
        )
    assert results == [204, 204]
    with SessionLocal() as session:
        row = session.get_one(NotificationOutbox, notification_id)
        assert row.provider_delivery_state == "DELIVERED"
        assert row.provider_event_at == now - timedelta(minutes=1)
    setup_client.close()
    get_settings.cache_clear()
    client = iam_support.new_client()
    user_id = iam_support.register_verify_login(client)
    notification_id = uuid4()
    claim_token = uuid4()
    provider_message_id = f"message-{notification_id}"
    now = datetime.now(UTC)
    prelink_times = {
        "email.sent": now - timedelta(minutes=4),
        "email.delivery_delayed": now - timedelta(minutes=3),
        "email.delivered": now - timedelta(minutes=2),
        "email.complained": now - timedelta(minutes=1),
    }
    with SessionLocal() as session, session.begin():
        session.add(
            NotificationOutbox(
                id=notification_id,
                dedupe_key=f"test-race:{notification_id}",
                event_type="OFFER_AVAILABLE",
                recipient_user_id=user_id,
                resource_type="OFFER",
                resource_id=uuid4(),
                delivery_state=NotificationDeliveryState.CLAIMED,
                attempt_count=1,
                claim_token=claim_token,
                claimed_at=now,
            )
        )
        session.add_all(
            [
                NotificationProviderEvent(
                    provider="resend",
                    provider_event_id=f"event-{notification_id}-{index}",
                    provider_message_id=provider_message_id,
                    event_type=event_type,
                    occurred_at=prelink_times[event_type],
                )
                for index, event_type in enumerate(
                    [
                        "email.complained",
                        "email.sent",
                        "email.delivered",
                        "email.delivery_delayed",
                    ]
                )
            ]
        )
    with SessionLocal() as session:
        dispatcher = MarketplaceNotificationDispatcher(
            session, FakeMarketplaceNotificationSender(), Settings()
        )
        claimed = ClaimedNotification(
            id=notification_id,
            claim_token=claim_token,
            event=None,
            recipient_user_id=user_id,
            resource_type="OFFER",
            resource_id=uuid4(),
            attempt_count=1,
        )
        assert dispatcher._mark_delivered(claimed, now, provider_message_id)
    with SessionLocal() as session:
        row = session.get_one(NotificationOutbox, notification_id)
        assert row.provider_delivery_state == "COMPLAINED"
        assert row.provider_event_at == prelink_times["email.complained"]
    client.close()
    client = iam_support.new_client()
    user_id = iam_support.register_verify_login(client)
    notification_id = uuid4()
    provider_message_id = f"message-{notification_id}"
    event_prefix = str(notification_id)
    with SessionLocal() as session, session.begin():
        session.add(
            NotificationOutbox(
                id=notification_id,
                dedupe_key=f"test:{notification_id}",
                event_type="OFFER_AVAILABLE",
                recipient_user_id=user_id,
                resource_type="OFFER",
                resource_id=uuid4(),
                delivery_state=NotificationDeliveryState.DELIVERED,
                provider_message_id=provider_message_id,
                provider_delivery_state="ACCEPTED",
            )
        )

    def post(
        event_id: str,
        event_type: str,
        message_id: str,
        occurred_at: datetime,
    ):
        timestamp = str(int(datetime.now(UTC).timestamp()))
        body = json.dumps(
            {
                "type": event_type,
                "created_at": occurred_at.isoformat(),
                "data": {"email_id": message_id},
            },
            separators=(",", ":"),
        ).encode()
        return client.post(
            "/api/v1/webhooks/resend",
            content=body,
            headers={
                "content-type": "application/json",
                "svix-id": event_id,
                "svix-timestamp": timestamp,
                "svix-signature": _signature(secret, event_id, timestamp, body),
            },
        )

    t1 = datetime.now(UTC) - timedelta(minutes=4)
    t2 = t1 + timedelta(minutes=1)
    t3 = t2 + timedelta(minutes=1)
    t4 = t3 + timedelta(minutes=1)
    assert post(f"{event_prefix}-1", "email.delivered", provider_message_id, t3).status_code == 204
    # Same event identity is immutable even if replayed with different content.
    assert post(f"{event_prefix}-1", "email.complained", provider_message_id, t4).status_code == 204
    assert post(f"{event_prefix}-2", "email.complained", "wrong-message", t4).status_code == 204
    # An older higher-risk event remains in the ledger but cannot falsify the latest fact.
    assert post(f"{event_prefix}-3", "email.complained", provider_message_id, t2).status_code == 204
    with SessionLocal() as session:
        after_older = session.get_one(NotificationOutbox, notification_id)
        assert after_older.provider_delivery_state == "DELIVERED"
        assert after_older.provider_event_at == t3
    # A truthful later complaint escalates after delivery.
    assert post(f"{event_prefix}-4", "email.complained", provider_message_id, t4).status_code == 204
    assert post(f"{event_prefix}-5", "email.delivered", provider_message_id, t3).status_code == 204
    with SessionLocal() as session:
        row = session.scalar(
            select(NotificationOutbox).where(NotificationOutbox.id == notification_id)
        )
        assert row is not None
        assert row.provider_delivery_state == "COMPLAINED"
        assert row.provider_event_at == t4
    assert (
        post(
            f"{event_prefix}-future",
            "email.delivered",
            provider_message_id,
            datetime.now(UTC) + timedelta(minutes=6),
        ).status_code
        == 400
    )
    assert (
        post(
            f"{event_prefix}-naive",
            "email.delivered",
            provider_message_id,
            datetime.now().replace(tzinfo=None),
        ).status_code
        == 400
    )
    get_settings.cache_clear()
