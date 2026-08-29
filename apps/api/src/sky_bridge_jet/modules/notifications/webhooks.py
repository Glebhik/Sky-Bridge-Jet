from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from sky_bridge_jet.core.config import Settings, get_settings
from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.notifications.domain import (
    PROVIDER_EVENT_STATES,
    provider_delivery_should_advance,
)
from sky_bridge_jet.modules.notifications.models import (
    NotificationOutbox,
    NotificationProviderEvent,
)

router = APIRouter(prefix="/webhooks", tags=["provider-webhooks"])
MAX_WEBHOOK_BYTES = 64 * 1024
MAX_WEBHOOK_AGE_SECONDS = 300
MAX_PROVIDER_EVENT_FUTURE_SKEW = timedelta(minutes=5)


def _verify(secret: str, event_id: str, timestamp: str, signature: str, body: bytes) -> None:
    try:
        timestamp_value = int(timestamp)
        key = base64.b64decode(secret.removeprefix("whsec_"), validate=True)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook"
        ) from None
    now = int(datetime.now(UTC).timestamp())
    if abs(now - timestamp_value) > MAX_WEBHOOK_AGE_SECONDS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook")
    signed = event_id.encode() + b"." + timestamp.encode() + b"." + body
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    candidates = [part[3:] for part in signature.split() if part.startswith("v1,")]
    if not any(hmac.compare_digest(expected, candidate) for candidate in candidates):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook")


@router.post("/resend", status_code=status.HTTP_204_NO_CONTENT)
async def resend_webhook(
    request: Request,
    svix_id: str | None = Header(default=None),
    svix_timestamp: str | None = Header(default=None),
    svix_signature: str | None = Header(default=None),
) -> Response:
    settings: Settings = get_settings()
    if (
        not settings.resend_webhook_secret
        or not svix_id
        or not svix_timestamp
        or not svix_signature
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook")
    try:
        content_length = int(request.headers.get("content-length", "0") or 0)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook"
        ) from None
    if content_length < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook")
    if content_length > MAX_WEBHOOK_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Payload too large"
        )
    body = await request.body()
    if len(body) > MAX_WEBHOOK_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Payload too large"
        )
    _verify(settings.resend_webhook_secret, svix_id, svix_timestamp, svix_signature, body)
    try:
        payload = json.loads(body)
        provider_event = payload["type"]
        provider_message_id = payload["data"]["email_id"]
        occurred_at = datetime.fromisoformat(payload["created_at"].replace("Z", "+00:00"))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook"
        ) from None
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook")
    occurred_at = occurred_at.astimezone(UTC)
    if occurred_at > datetime.now(UTC) + MAX_PROVIDER_EVENT_FUTURE_SKEW:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook")
    state = PROVIDER_EVENT_STATES.get(provider_event)
    if (
        state is None
        or len(svix_id) > 255
        or not isinstance(provider_message_id, str)
        or len(provider_message_id) > 255
    ):
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    with SessionLocal() as session, session.begin():
        inserted = session.scalar(
            insert(NotificationProviderEvent)
            .values(
                provider="resend",
                provider_event_id=svix_id,
                provider_message_id=provider_message_id,
                event_type=provider_event,
                occurred_at=occurred_at,
            )
            .on_conflict_do_nothing(index_elements=[NotificationProviderEvent.provider_event_id])
            .returning(NotificationProviderEvent.id)
        )
        if inserted is None:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        notification = session.scalar(
            select(NotificationOutbox)
            .where(NotificationOutbox.provider_message_id == provider_message_id)
            .with_for_update()
        )
        if notification is not None and provider_delivery_should_advance(
            current_state=notification.provider_delivery_state,
            current_occurred_at=notification.provider_event_at,
            candidate_state=state,
            candidate_occurred_at=occurred_at,
        ):
            notification.provider_delivery_state = state.value
            notification.provider_event_at = occurred_at
    return Response(status_code=status.HTTP_204_NO_CONTENT)
