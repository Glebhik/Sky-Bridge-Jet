from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sky_bridge_jet.modules.payments.domain import PaymentOperationResult, PaymentOperationType
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
        # ``populate_existing`` is essential when this Session already loaded the
        # row during create-or-reuse: a concurrent command may have committed while
        # we waited for the lock, and returning that identity-map snapshot would
        # expose stale financial state even though the provider call was serialized.
        return self.session.get(Payment, payment_id, populate_existing=True, with_for_update=True)

    def get_by_booking(self, booking_id: UUID) -> Payment | None:
        return self.session.scalar(select(Payment).where(Payment.booking_id == booking_id))

    def get_by_booking_for_update(self, booking_id: UUID) -> Payment | None:
        statement = (
            select(Payment)
            .where(Payment.booking_id == booking_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return self.session.scalar(statement)


class PaymentOperationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, operation: PaymentOperation) -> PaymentOperation:
        self.session.add(operation)
        return operation

    def lock_idempotency_key(self, idempotency_key: str) -> None:
        """Serialize global use of one key for the current transaction.

        The operation table's unique constraint remains the persistence backstop;
        this transaction-scoped PostgreSQL lock closes the preflight-SELECT race
        before a provider financial action can be attempted for the same key.
        """
        self.session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(idempotency_key, 0)))
        )

    def get_by_idempotency_key(self, idempotency_key: str) -> PaymentOperation | None:
        return self.session.scalar(
            select(PaymentOperation).where(PaymentOperation.idempotency_key == idempotency_key)
        )

    def get_by_correlation_id(self, correlation_id: UUID) -> PaymentOperation | None:
        return self.session.scalar(
            select(PaymentOperation)
            .where(PaymentOperation.correlation_id == correlation_id)
            .with_for_update()
        )

    def get_unresolved(
        self, payment_id: UUID, operation: PaymentOperationType
    ) -> PaymentOperation | None:
        return self.session.scalar(
            select(PaymentOperation).where(
                PaymentOperation.payment_id == payment_id,
                PaymentOperation.operation == operation,
                PaymentOperation.result.in_(
                    [PaymentOperationResult.PENDING, PaymentOperationResult.UNKNOWN]
                ),
            )
        )

    def get_any_unresolved(self, payment_id: UUID) -> PaymentOperation | None:
        return self.session.scalar(
            select(PaymentOperation).where(
                PaymentOperation.payment_id == payment_id,
                PaymentOperation.result.in_(
                    [PaymentOperationResult.PENDING, PaymentOperationResult.UNKNOWN]
                ),
            )
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
