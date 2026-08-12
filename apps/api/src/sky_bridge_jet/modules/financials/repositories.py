from __future__ import annotations

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from sky_bridge_jet.modules.financials.models import (
    OperatorConnectedAccount,
    ProviderWebhookEvent,
)
from sky_bridge_jet.modules.payments.domain import PaymentProviderKind


class OperatorConnectedAccountRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, account: OperatorConnectedAccount) -> OperatorConnectedAccount:
        self.session.add(account)
        return account

    def get(
        self, operator_id: UUID, provider: PaymentProviderKind
    ) -> OperatorConnectedAccount | None:
        return self.session.scalar(self._by_operator(operator_id, provider))

    def get_for_update(
        self, operator_id: UUID, provider: PaymentProviderKind
    ) -> OperatorConnectedAccount | None:
        return self.session.scalar(self._by_operator(operator_id, provider).with_for_update())

    def get_by_reference_for_update(
        self, provider: PaymentProviderKind, provider_account_reference: str
    ) -> OperatorConnectedAccount | None:
        statement = (
            select(OperatorConnectedAccount)
            .where(
                OperatorConnectedAccount.payment_provider == provider.value,
                OperatorConnectedAccount.provider_account_reference == provider_account_reference,
            )
            .with_for_update()
        )
        return self.session.scalar(statement)

    @staticmethod
    def _by_operator(
        operator_id: UUID, provider: PaymentProviderKind
    ) -> Select[tuple[OperatorConnectedAccount]]:
        return select(OperatorConnectedAccount).where(
            OperatorConnectedAccount.operator_id == operator_id,
            OperatorConnectedAccount.payment_provider == provider.value,
        )


class ProviderWebhookEventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, event: ProviderWebhookEvent) -> ProviderWebhookEvent:
        self.session.add(event)
        return event

    def get(
        self, provider: PaymentProviderKind, provider_event_id: str
    ) -> ProviderWebhookEvent | None:
        return self.session.scalar(
            select(ProviderWebhookEvent).where(
                ProviderWebhookEvent.payment_provider == provider.value,
                ProviderWebhookEvent.provider_event_id == provider_event_id,
            )
        )
