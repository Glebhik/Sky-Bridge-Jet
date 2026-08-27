from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sky_bridge_jet.modules.financials.domain import (
    ProviderAccountSnapshot,
    WebhookProcessingStatus,
)
from sky_bridge_jet.modules.financials.models import ProviderWebhookEvent
from sky_bridge_jet.modules.financials.repositories import (
    OperatorConnectedAccountRepository,
    ProviderWebhookEventRepository,
)
from sky_bridge_jet.modules.financials.services import _apply_snapshot
from sky_bridge_jet.modules.payments.domain import PaymentProviderKind
from sky_bridge_jet.modules.payments.reconciliation import (
    ProviderPaymentEvent,
    apply_provider_payment_event,
)

_PAYMENT_EVENTS = {
    "payment_intent.amount_capturable_updated": ProviderPaymentEvent.AUTHORIZED,
    "payment_intent.payment_failed": ProviderPaymentEvent.AUTHORIZATION_FAILED,
    "payment_intent.succeeded": ProviderPaymentEvent.CAPTURED,
    "payment_intent.canceled": ProviderPaymentEvent.CANCELLED,
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class NormalizedProviderEvent:
    provider: PaymentProviderKind
    event_id: str
    event_type: str
    object_id: str | None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WebhookProcessingResult:
    status: WebhookProcessingStatus
    duplicate: bool


class WebhookReconciliationService:
    """Provider-neutral, idempotent webhook reconciliation.

    A verified provider event is normalized upstream (signature verification in the
    adapter) and applied here. Unique (provider, event_id) makes duplicate/replayed
    deliveries safe; only allowed domain transitions are applied, so out-of-order
    events never corrupt money totals or regress state.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.events = ProviderWebhookEventRepository(session)
        self.accounts = OperatorConnectedAccountRepository(session)

    def process(self, event: NormalizedProviderEvent) -> WebhookProcessingResult:
        try:
            with self.session.begin():
                if self.events.get(event.provider, event.event_id) is not None:
                    return WebhookProcessingResult(
                        WebhookProcessingStatus.PROCESSED, duplicate=True
                    )
                row = self.events.add(
                    ProviderWebhookEvent(
                        payment_provider=event.provider.value,
                        provider_event_id=event.event_id,
                        event_type=event.event_type,
                        status=WebhookProcessingStatus.RECEIVED,
                    )
                )
                self.session.flush()
                self._dispatch(event, row)
                row.processed_at = _utc_now()
                self.session.flush()
                return WebhookProcessingResult(row.status, duplicate=False)
        except IntegrityError:
            # A concurrent duplicate delivery lost the unique-constraint race.
            return WebhookProcessingResult(WebhookProcessingStatus.PROCESSED, duplicate=True)

    def _dispatch(self, event: NormalizedProviderEvent, row: ProviderWebhookEvent) -> None:
        payment_event = _PAYMENT_EVENTS.get(event.event_type)
        if payment_event is not None and event.object_id is not None:
            changed = apply_provider_payment_event(
                self.session,
                provider_reference=event.object_id,
                event=payment_event,
                provider_status=event.data.get("status"),
                operation_correlation=(event.data.get("metadata") or {}).get(
                    "operation_correlation"
                ),
            )
            row.entity_reference = str(changed) if changed is not None else event.object_id
            row.status = WebhookProcessingStatus.PROCESSED
            return

        if event.event_type == "account.updated" and event.object_id is not None:
            account = self.accounts.get_by_reference_for_update(event.provider, event.object_id)
            if account is not None:
                _apply_snapshot(account, self._account_snapshot(event.data))
                row.entity_reference = str(account.id)
                row.status = WebhookProcessingStatus.PROCESSED
            else:
                row.status = WebhookProcessingStatus.IGNORED
            return

        if event.event_type == "charge.refunded":
            # The domain refund command is authoritative for amounts; the event is
            # recorded as evidence only, never re-applying a refund.
            row.entity_reference = event.object_id
            row.status = WebhookProcessingStatus.PROCESSED
            return

        row.status = WebhookProcessingStatus.IGNORED

    @staticmethod
    def _account_snapshot(data: dict[str, Any]) -> ProviderAccountSnapshot:
        requirements = data.get("requirements") or {}
        return ProviderAccountSnapshot(
            charges_enabled=bool(data.get("charges_enabled")),
            payouts_enabled=bool(data.get("payouts_enabled")),
            details_submitted=bool(data.get("details_submitted")),
            requirements_due=bool(requirements.get("currently_due")),
            disabled_reason=requirements.get("disabled_reason"),
        )
