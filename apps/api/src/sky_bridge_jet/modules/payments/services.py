from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from sky_bridge_jet.modules.bookings.domain import BookingStatus
from sky_bridge_jet.modules.bookings.repositories import BookingRepository
from sky_bridge_jet.modules.core_aviation.domain import ResourceNotFoundError
from sky_bridge_jet.modules.payments.domain import (
    IdempotencyConflictError,
    InvalidPaymentStateError,
    PaymentEligibilityError,
    PaymentOperationResult,
    PaymentOperationType,
    PaymentStatus,
    SettlementEligibility,
    compute_settlement_eligibility,
    generate_payment_reference,
    is_authorizable,
    is_booking_payable,
    is_capturable,
    is_refundable,
    is_voidable,
    refund_status_after,
    validate_payment_transition,
)
from sky_bridge_jet.modules.payments.models import Payment, PaymentOperation
from sky_bridge_jet.modules.payments.provider import (
    PaymentProvider,
    ProviderOutcome,
    get_payment_provider,
)
from sky_bridge_jet.modules.payments.repositories import (
    PaymentOperationRepository,
    PaymentRepository,
)
from sky_bridge_jet.modules.payments.schemas import (
    PaymentAuthorize,
    PaymentCapture,
    PaymentVoid,
    RefundCreate,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _not_found(resource_name: str) -> ResourceNotFoundError:
    return ResourceNotFoundError(f"{resource_name} was not found")


class PaymentService:
    """Own payment orchestration within one explicit transaction per command.

    Authorization is intentionally deferred for Phase 5. The provider is a
    deterministic fake — no real money moves. Financial success is recorded from
    the provider result, never inferred from booking state. Idempotency keys make
    commands safe to retry.
    """

    def __init__(self, session: Session, provider: PaymentProvider | None = None) -> None:
        self.session = session
        self.payments = PaymentRepository(session)
        self.operations = PaymentOperationRepository(session)
        self.bookings = BookingRepository(session)
        self.provider = provider if provider is not None else get_payment_provider()

    # -- Creation -----------------------------------------------------------

    def create_for_booking(self, booking_id: UUID) -> Payment:
        """Create the single payment for a booking; idempotent per booking."""
        with self.session.begin():
            booking = self.bookings.get_for_update(booking_id)
            if booking is None:
                raise _not_found("Booking")
            if not is_booking_payable(booking.status):
                raise PaymentEligibilityError("Booking is not eligible for payment")

            existing = self.payments.get_by_booking(booking_id)
            if existing is not None:
                return existing

            payment = self.payments.add(
                Payment(
                    reference=generate_payment_reference(),
                    booking_id=booking.id,
                    status=PaymentStatus.CREATED,
                    currency=booking.currency,
                    operator_amount_minor=booking.operator_amount_minor,
                    platform_fee_minor=booking.platform_fee_minor,
                    tax_amount_minor=booking.tax_amount_minor,
                    total_amount_minor=booking.total_amount_minor,
                    captured_amount_minor=0,
                    refunded_amount_minor=0,
                )
            )
            self.session.flush()
            return payment

    # -- Financial commands -------------------------------------------------

    def authorize(self, payment_id: UUID, data: PaymentAuthorize) -> Payment:
        with self.session.begin():
            payment = self.payments.get_for_update(payment_id)
            if payment is None:
                raise _not_found("Payment")
            if self._replay(data.idempotency_key, payment, PaymentOperationType.AUTHORIZE):
                return payment

            booking = self.bookings.get(payment.booking_id)
            if booking is None:
                raise _not_found("Booking")
            if booking.status in {BookingStatus.REJECTED, BookingStatus.CANCELLED}:
                raise PaymentEligibilityError("Booking is not eligible for authorization")
            if not is_authorizable(payment.status):
                raise InvalidPaymentStateError("Payment cannot be authorized in its current state")

            result = self.provider.authorize(
                amount_minor=payment.total_amount_minor,
                currency=payment.currency,
                payment_method_reference=data.payment_method_reference,
            )
            if result.outcome is ProviderOutcome.FAILED:
                payment.status = validate_payment_transition(
                    payment.status, PaymentStatus.AUTHORIZATION_FAILED
                )
                self._record(
                    payment,
                    PaymentOperationType.AUTHORIZE,
                    PaymentOperationResult.FAILED,
                    data.idempotency_key,
                    amount_minor=payment.total_amount_minor,
                    provider_reference=result.provider_reference,
                    failure_code=result.failure_code,
                )
            else:
                payment.status = validate_payment_transition(
                    payment.status, PaymentStatus.AUTHORIZED
                )
                payment.authorized_amount_minor = payment.total_amount_minor
                payment.provider_payment_reference = result.provider_reference
                payment.authorized_at = _utc_now()
                self._record(
                    payment,
                    PaymentOperationType.AUTHORIZE,
                    PaymentOperationResult.SUCCEEDED,
                    data.idempotency_key,
                    amount_minor=payment.total_amount_minor,
                    provider_reference=result.provider_reference,
                )
            self.session.flush()
            return payment

    def capture(self, payment_id: UUID, data: PaymentCapture) -> Payment:
        with self.session.begin():
            payment = self.payments.get_for_update(payment_id)
            if payment is None:
                raise _not_found("Payment")
            if self._replay(data.idempotency_key, payment, PaymentOperationType.CAPTURE):
                return payment

            # Lock the booking row so a concurrent cancellation cannot interleave.
            booking = self.bookings.get_for_update(payment.booking_id)
            if booking is None:
                raise _not_found("Booking")
            if booking.status is not BookingStatus.CONFIRMED:
                raise PaymentEligibilityError("Capture requires a confirmed booking")
            if not is_capturable(payment.status):
                raise InvalidPaymentStateError("Payment cannot be captured in its current state")
            if (
                payment.provider_payment_reference is None
                or payment.authorized_amount_minor is None
            ):
                raise InvalidPaymentStateError("Payment has no authorization to capture")

            result = self.provider.capture(
                provider_reference=payment.provider_payment_reference,
                amount_minor=payment.authorized_amount_minor,
                currency=payment.currency,
            )
            if result.outcome is ProviderOutcome.FAILED:
                payment.status = validate_payment_transition(
                    payment.status, PaymentStatus.CAPTURE_FAILED
                )
                self._record(
                    payment,
                    PaymentOperationType.CAPTURE,
                    PaymentOperationResult.FAILED,
                    data.idempotency_key,
                    amount_minor=payment.authorized_amount_minor,
                    provider_reference=result.provider_reference,
                    failure_code=result.failure_code,
                )
            else:
                payment.status = validate_payment_transition(payment.status, PaymentStatus.CAPTURED)
                payment.captured_amount_minor = payment.authorized_amount_minor
                payment.captured_at = _utc_now()
                if result.provider_reference is not None:
                    payment.provider_payment_reference = result.provider_reference
                self._record(
                    payment,
                    PaymentOperationType.CAPTURE,
                    PaymentOperationResult.SUCCEEDED,
                    data.idempotency_key,
                    amount_minor=payment.captured_amount_minor,
                    provider_reference=result.provider_reference,
                )
            self.session.flush()
            return payment

    def void(self, payment_id: UUID, data: PaymentVoid) -> Payment:
        with self.session.begin():
            payment = self.payments.get_for_update(payment_id)
            if payment is None:
                raise _not_found("Payment")
            if self._replay(data.idempotency_key, payment, PaymentOperationType.VOID):
                return payment
            if not is_voidable(payment.status):
                raise InvalidPaymentStateError("Payment cannot be voided in its current state")

            provider_reference = payment.provider_payment_reference
            if payment.status is PaymentStatus.AUTHORIZED and provider_reference is not None:
                result = self.provider.void(provider_reference=provider_reference)
                provider_reference = result.provider_reference

            payment.status = validate_payment_transition(payment.status, PaymentStatus.CANCELLED)
            payment.cancelled_at = _utc_now()
            self._record(
                payment,
                PaymentOperationType.VOID,
                PaymentOperationResult.SUCCEEDED,
                data.idempotency_key,
                amount_minor=payment.authorized_amount_minor or 0,
                provider_reference=provider_reference,
            )
            self.session.flush()
            return payment

    def refund(self, payment_id: UUID, data: RefundCreate) -> PaymentOperation:
        with self.session.begin():
            payment = self.payments.get_for_update(payment_id)
            if payment is None:
                raise _not_found("Payment")
            replay = self._replay_operation(
                data.idempotency_key, payment, PaymentOperationType.REFUND
            )
            if replay is not None:
                return replay
            if not is_refundable(payment.status):
                raise InvalidPaymentStateError("Payment cannot be refunded in its current state")

            remaining = payment.captured_amount_minor - payment.refunded_amount_minor
            if data.amount_minor > remaining:
                raise PaymentEligibilityError("Refund exceeds the remaining captured amount")

            result = self.provider.refund(
                provider_reference=payment.provider_payment_reference or "",
                amount_minor=data.amount_minor,
                currency=payment.currency,
            )
            if result.outcome is ProviderOutcome.FAILED:
                return self._record(
                    payment,
                    PaymentOperationType.REFUND,
                    PaymentOperationResult.FAILED,
                    data.idempotency_key,
                    amount_minor=data.amount_minor,
                    provider_reference=result.provider_reference,
                    failure_code=result.failure_code,
                )

            payment.refunded_amount_minor += data.amount_minor
            payment.status = validate_payment_transition(
                payment.status,
                refund_status_after(
                    captured_minor=payment.captured_amount_minor,
                    refunded_minor=payment.refunded_amount_minor,
                ),
            )
            operation = self._record(
                payment,
                PaymentOperationType.REFUND,
                PaymentOperationResult.SUCCEEDED,
                data.idempotency_key,
                amount_minor=data.amount_minor,
                provider_reference=result.provider_reference,
            )
            self.session.flush()
            return operation

    # -- Reads --------------------------------------------------------------

    def get(self, payment_id: UUID) -> Payment:
        payment = self.payments.get(payment_id)
        if payment is None:
            raise _not_found("Payment")
        return payment

    def get_for_booking(self, booking_id: UUID) -> Payment:
        if self.bookings.get(booking_id) is None:
            raise _not_found("Booking")
        payment = self.payments.get_by_booking(booking_id)
        if payment is None:
            raise _not_found("Payment")
        return payment

    def list_refunds(self, payment_id: UUID) -> list[PaymentOperation]:
        self.get(payment_id)
        return list(self.operations.list_refunds(payment_id))

    def get_allocation(self, payment_id: UUID) -> tuple[Payment, SettlementEligibility]:
        payment = self.get(payment_id)
        booking = self.bookings.get(payment.booking_id)
        if booking is None:
            raise _not_found("Booking")
        eligibility = compute_settlement_eligibility(
            payment_status=payment.status,
            booking_status=booking.status,
            captured_minor=payment.captured_amount_minor,
            refunded_minor=payment.refunded_amount_minor,
        )
        return payment, eligibility

    # -- Idempotency helpers ------------------------------------------------

    def _replay(
        self, idempotency_key: str, payment: Payment, operation: PaymentOperationType
    ) -> bool:
        return self._replay_operation(idempotency_key, payment, operation) is not None

    def _replay_operation(
        self, idempotency_key: str, payment: Payment, operation: PaymentOperationType
    ) -> PaymentOperation | None:
        existing = self.operations.get_by_idempotency_key(idempotency_key)
        if existing is None:
            return None
        if existing.payment_id != payment.id or existing.operation is not operation:
            raise IdempotencyConflictError(
                "Idempotency key has already been used for a different operation"
            )
        return existing

    def _record(
        self,
        payment: Payment,
        operation: PaymentOperationType,
        result: PaymentOperationResult,
        idempotency_key: str,
        *,
        amount_minor: int,
        provider_reference: str | None,
        failure_code: str | None = None,
    ) -> PaymentOperation:
        return self.operations.add(
            PaymentOperation(
                payment=payment,
                operation=operation,
                result=result,
                idempotency_key=idempotency_key,
                amount_minor=amount_minor,
                provider_reference=provider_reference,
                failure_code=failure_code,
            )
        )
