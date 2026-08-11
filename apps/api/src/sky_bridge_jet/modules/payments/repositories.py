from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sky_bridge_jet.modules.payments.domain import PaymentOperationType
from sky_bridge_jet.modules.payments.models import Payment, PaymentOperation


class PaymentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, payment: Payment) -> Payment:
        self.session.add(payment)
        return payment

    def get(self, payment_id: UUID) -> Payment | None:
        return self.session.get(Payment, payment_id)

    def get_for_update(self, payment_id: UUID) -> Payment | None:
        """Load a payment with a row lock so financial commands serialize."""
        return self.session.get(Payment, payment_id, with_for_update=True)

    def get_by_booking(self, booking_id: UUID) -> Payment | None:
        return self.session.scalar(select(Payment).where(Payment.booking_id == booking_id))

    def get_by_booking_for_update(self, booking_id: UUID) -> Payment | None:
        statement = select(Payment).where(Payment.booking_id == booking_id).with_for_update()
        return self.session.scalar(statement)


class PaymentOperationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, operation: PaymentOperation) -> PaymentOperation:
        self.session.add(operation)
        return operation

    def get_by_idempotency_key(self, idempotency_key: str) -> PaymentOperation | None:
        return self.session.scalar(
            select(PaymentOperation).where(PaymentOperation.idempotency_key == idempotency_key)
        )

    def list_refunds(self, payment_id: UUID) -> Sequence[PaymentOperation]:
        statement = (
            select(PaymentOperation)
            .where(
                PaymentOperation.payment_id == payment_id,
                PaymentOperation.operation == PaymentOperationType.REFUND,
            )
            .order_by(PaymentOperation.created_at.asc(), PaymentOperation.id.asc())
        )
        return self.session.scalars(statement).all()
