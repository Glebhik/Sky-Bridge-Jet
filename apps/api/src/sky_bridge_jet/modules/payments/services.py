from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from sky_bridge_jet.core.config import Settings, get_settings
from sky_bridge_jet.core.stripe_gateway import build_stripe_gateway
from sky_bridge_jet.modules.bookings.domain import BookingStatus
from sky_bridge_jet.modules.bookings.models import Booking
from sky_bridge_jet.modules.bookings.repositories import BookingRepository
from sky_bridge_jet.modules.core_aviation.domain import ResourceNotFoundError
from sky_bridge_jet.modules.payments.domain import (
    IdempotencyConflictError,
    InvalidPaymentStateError,
    PaymentEligibilityError,
    PaymentOperationResult,
    PaymentOperationType,
    PaymentProviderKind,
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
    PaymentProviderError,
    ProviderOutcome,
    get_payment_provider,
)
from sky_bridge_jet.modules.payments.repositories import (
    PaymentOperationRepository,
    PaymentRepository,
)
from sky_bridge_jet.modules.payments.schemas import (
    CustomerPaymentInitiate,
    PaymentAuthorize,
    PaymentCapture,
    PaymentVoid,
    RefundCreate,
)
from sky_bridge_jet.modules.payments.stripe_adapter import StripeConnectPaymentProvider


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _not_found(resource_name: str) -> ResourceNotFoundError:
    return ResourceNotFoundError(f"{resource_name} was not found")


# Optional append-only audit hook the router supplies; the service runs it inside the
# command transaction and only on the success path (Phase 9.0.A-3 payment-operation
# auditing), so the security record commits atomically with the mutation and a
# failed/declined/replayed operation records nothing.
OnCommit = Callable[[Session], None] | None


class PaymentService:
    """Own payment orchestration within one explicit transaction per command.

    Authorization is intentionally deferred for Phase 5. The provider is a
    deterministic fake — no real money moves. Financial success is recorded from
    the provider result, never inferred from booking state. Idempotency keys make
    commands safe to retry.
    """

    def __init__(
        self,
        session: Session,
        provider: PaymentProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.payments = PaymentRepository(session)
        self.operations = PaymentOperationRepository(session)
        self.bookings = BookingRepository(session)
        # An explicit provider overrides per-payment resolution (used by tests and
        # by callers that inject a mocked Stripe boundary). Otherwise the provider
        # is resolved per payment from its stored ``payment_provider`` kind, so a
        # FAKE payment never touches Stripe even when Stripe is enabled globally.
        self._provider_override = provider
        self.settings = settings or get_settings()

    def _provider_for(self, payment: Payment) -> PaymentProvider:
        """Resolve the provider adapter for a single payment.

        The kind is pinned on the payment row at creation, so authorize/capture/
        refund always route to the same provider that created the intent — even if
        global configuration changes between commands.
        """
        if self._provider_override is not None:
            return self._provider_override
        if payment.payment_provider is PaymentProviderKind.STRIPE:
            return StripeConnectPaymentProvider(
                build_stripe_gateway(self.settings.stripe_secret_key)
            )
        return get_payment_provider()

    def _selected_provider_kind(
        self, provider_kind: PaymentProviderKind | None
    ) -> PaymentProviderKind:
        if provider_kind is not None:
            return provider_kind
        if self._provider_override is not None:
            return self._provider_override.kind
        return (
            PaymentProviderKind.STRIPE if self.settings.stripe_enabled else PaymentProviderKind.FAKE
        )

    # -- Creation -----------------------------------------------------------

    def create_for_booking(
        self,
        booking_id: UUID,
        *,
        provider_kind: PaymentProviderKind | None = None,
        on_commit: OnCommit = None,
    ) -> Payment:
        """Create the single payment for a booking; idempotent per booking."""
        with self.session.begin():
            return self._create_for_booking_locked(
                booking_id, provider_kind=provider_kind, on_commit=on_commit
            )

    def _create_for_booking_locked(
        self,
        booking_id: UUID,
        *,
        provider_kind: PaymentProviderKind | None = None,
        on_commit: OnCommit = None,
    ) -> Payment:
        booking = self.bookings.get_for_update(booking_id)
        if booking is None:
            raise _not_found("Booking")
        if not is_booking_payable(booking.status):
            raise PaymentEligibilityError("Booking is not eligible for payment")
        existing = self.payments.get_by_booking_for_update(booking_id)
        if existing is not None:
            return existing
        kind = self._selected_provider_kind(provider_kind)
        if kind is PaymentProviderKind.STRIPE:
            from sky_bridge_jet.modules.financials.services import evaluate_financial_eligibility

            decision = evaluate_financial_eligibility(self.session, booking.operator_id, kind)
            if not decision.eligible:
                raise PaymentEligibilityError(
                    "Operator is not financially onboarded for PSP-backed payments"
                )
        payment = self.payments.add(
            Payment(
                reference=generate_payment_reference(),
                booking_id=booking.id,
                status=PaymentStatus.CREATED,
                currency=booking.currency,
                payment_provider=kind,
                operator_amount_minor=booking.operator_amount_minor,
                platform_fee_minor=booking.platform_fee_minor,
                tax_amount_minor=booking.tax_amount_minor,
                total_amount_minor=booking.total_amount_minor,
                captured_amount_minor=0,
                refunded_amount_minor=0,
            )
        )
        self.session.flush()
        if on_commit is not None:
            on_commit(self.session)
        return payment

    # -- Financial commands -------------------------------------------------

    def initiate_for_customer(
        self, booking_id: UUID, data: CustomerPaymentInitiate, *, on_commit: OnCommit = None
    ) -> Payment:
        """Create/reuse a payment, then run the durable authorization attempt."""
        with self.session.begin():
            booking = self.bookings.get_for_update(booking_id)
            if booking is None:
                raise _not_found("Booking")
            if not is_booking_payable(booking.status):
                raise PaymentEligibilityError("Booking is not eligible for payment")
            payment = self.payments.get_by_booking_for_update(booking_id)
            self.operations.lock_idempotency_key(data.idempotency_key)
            operation = self.operations.get_by_idempotency_key(data.idempotency_key)
            if operation is not None and (
                payment is None
                or operation.payment_id != payment.id
                or operation.operation is not PaymentOperationType.AUTHORIZE
            ):
                raise IdempotencyConflictError(
                    "Idempotency key has already been used for a different operation"
                )
            if payment is None:
                payment = self._create_for_booking_locked(booking_id)
            unresolved = self.operations.get_unresolved(payment.id, PaymentOperationType.AUTHORIZE)
            if unresolved is not None and unresolved.idempotency_key != data.idempotency_key:
                # A different key cannot start a second intent while the durable
                # logical authorization attempt is unresolved.
                return payment
            if operation is not None and operation.result in {
                PaymentOperationResult.SUCCEEDED,
                PaymentOperationResult.FAILED,
            }:
                return payment
            if (
                payment.status
                in {
                    PaymentStatus.AUTHORIZED,
                    PaymentStatus.CAPTURED,
                    PaymentStatus.PARTIALLY_REFUNDED,
                    PaymentStatus.REFUNDED,
                }
                or payment.requires_customer_action
            ):
                return payment
            if payment.status is PaymentStatus.CANCELLED:
                raise InvalidPaymentStateError("Payment cannot be authorized in its current state")
            if operation is None:
                operation = self._record(
                    payment,
                    PaymentOperationType.AUTHORIZE,
                    PaymentOperationResult.PENDING,
                    data.idempotency_key,
                    amount_minor=payment.total_amount_minor,
                    provider_reference=None,
                )
                # Reservation is durable before dispatch; the dispatcher owns
                # incrementing the count for each actual provider attempt.
                operation.attempt_count = 0
                self.session.flush()
            payment_id = payment.id
        return self._authorize_durable(
            payment_id,
            PaymentAuthorize(idempotency_key=data.idempotency_key),
            on_commit=on_commit,
        )

    def authorize(
        self, payment_id: UUID, data: PaymentAuthorize, *, on_commit: OnCommit = None
    ) -> Payment:
        return self._authorize_durable(payment_id, data, on_commit=on_commit)

    def _authorize_durable(
        self, payment_id: UUID, data: PaymentAuthorize, *, on_commit: OnCommit = None
    ) -> Payment:
        """Reserve durably, dispatch outside a DB transaction, then reconcile."""
        with self.session.begin():
            payment = self.payments.get_for_update(payment_id)
            if payment is None:
                raise _not_found("Payment")
            existing = self._replay_operation(
                data.idempotency_key, payment, PaymentOperationType.AUTHORIZE
            )
            if existing is not None and existing.result in {
                PaymentOperationResult.SUCCEEDED,
                PaymentOperationResult.FAILED,
            }:
                return payment
            unresolved = self.operations.get_any_unresolved(payment.id)
            if unresolved is not None and unresolved.id != getattr(existing, "id", None):
                return payment
            booking = self.bookings.get(payment.booking_id)
            if booking is None:
                raise _not_found("Booking")
            if booking.status in {BookingStatus.REJECTED, BookingStatus.CANCELLED}:
                raise PaymentEligibilityError("Booking is not eligible for authorization")
            if existing is None:
                if (
                    payment.status
                    in {
                        PaymentStatus.AUTHORIZED,
                        PaymentStatus.CAPTURED,
                        PaymentStatus.PARTIALLY_REFUNDED,
                        PaymentStatus.REFUNDED,
                    }
                    or payment.requires_customer_action
                ):
                    return payment
                if not is_authorizable(payment.status):
                    raise InvalidPaymentStateError(
                        "Payment cannot be authorized in its current state"
                    )
                existing = self._record(
                    payment,
                    PaymentOperationType.AUTHORIZE,
                    PaymentOperationResult.PENDING,
                    data.idempotency_key,
                    amount_minor=payment.total_amount_minor,
                    provider_reference=None,
                )
                existing.attempt_count = 0
            else:
                existing.result = PaymentOperationResult.PENDING
                existing.failure_code = None
            existing.attempt_count += 1
            self.session.flush()
            provider = self._provider_for(payment)
            provider_key = str(existing.correlation_id)
            amount_minor = payment.total_amount_minor
            currency = payment.currency

        try:
            result = provider.authorize(
                amount_minor=amount_minor,
                currency=currency,
                payment_method_reference=data.payment_method_reference,
                idempotency_key=provider_key,
            )
        except PaymentProviderError:
            with self.session.begin():
                operation = self.operations.get_by_idempotency_key(data.idempotency_key)
                assert operation is not None
                operation.result = PaymentOperationResult.UNKNOWN
                operation.failure_code = "provider_outcome_unknown"
                payment = self.payments.get_for_update(payment_id)
                assert payment is not None
                self.session.flush()
                return payment

        with self.session.begin():
            payment = self.payments.get_for_update(payment_id)
            operation = self.operations.get_by_idempotency_key(data.idempotency_key)
            assert payment is not None and operation is not None
            payment.provider_status = result.provider_status
            operation.provider_reference = result.provider_reference
            if payment.status is PaymentStatus.AUTHORIZED:
                operation.result = PaymentOperationResult.SUCCEEDED
                operation.failure_code = None
                return payment
            if result.provider_reference is not None:
                payment.provider_payment_reference = result.provider_reference
            if result.outcome is ProviderOutcome.FAILED:
                payment.status = validate_payment_transition(
                    payment.status, PaymentStatus.AUTHORIZATION_FAILED
                )
                operation.result = PaymentOperationResult.FAILED
                operation.failure_code = result.failure_code
            elif result.outcome is ProviderOutcome.REQUIRES_ACTION:
                payment.requires_customer_action = True
                operation.result = PaymentOperationResult.PENDING
                payment.client_action = result.client_action
            else:
                payment.status = validate_payment_transition(
                    payment.status, PaymentStatus.AUTHORIZED
                )
                payment.authorized_amount_minor = payment.total_amount_minor
                payment.authorized_at = _utc_now()
                payment.requires_customer_action = False
                operation.result = PaymentOperationResult.SUCCEEDED
            self.session.flush()
            if on_commit is not None and operation.result is PaymentOperationResult.SUCCEEDED:
                on_commit(self.session)
            return payment

    def _authorize_locked(
        self, payment: Payment, data: PaymentAuthorize, *, on_commit: OnCommit = None
    ) -> Payment:
        if self._replay(data.idempotency_key, payment, PaymentOperationType.AUTHORIZE):
            return payment

        booking = self.bookings.get(payment.booking_id)
        if booking is None:
            raise _not_found("Booking")
        if booking.status in {BookingStatus.REJECTED, BookingStatus.CANCELLED}:
            raise PaymentEligibilityError("Booking is not eligible for authorization")
        if not is_authorizable(payment.status):
            raise InvalidPaymentStateError("Payment cannot be authorized in its current state")

        result = self._provider_for(payment).authorize(
            amount_minor=payment.total_amount_minor,
            currency=payment.currency,
            payment_method_reference=data.payment_method_reference,
            idempotency_key=data.idempotency_key,
        )
        payment.provider_status = result.provider_status
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
        elif result.outcome is ProviderOutcome.REQUIRES_ACTION:
            # SCA/3DS: the intent exists but authorization is not final until the
            # customer completes an action off-platform. The payment stays CREATED;
            # a later verified webhook transitions it to AUTHORIZED. We record the
            # command so a retry with the same key replays instead of re-creating
            # an intent, and expose the client action transiently (never persisted).
            payment.requires_customer_action = True
            payment.provider_payment_reference = result.provider_reference
            self._record(
                payment,
                PaymentOperationType.AUTHORIZE,
                PaymentOperationResult.SUCCEEDED,
                data.idempotency_key,
                amount_minor=payment.total_amount_minor,
                provider_reference=result.provider_reference,
            )
            payment.client_action = result.client_action
        else:
            payment.status = validate_payment_transition(payment.status, PaymentStatus.AUTHORIZED)
            payment.authorized_amount_minor = payment.total_amount_minor
            payment.provider_payment_reference = result.provider_reference
            payment.authorized_at = _utc_now()
            payment.requires_customer_action = False
            self._record(
                payment,
                PaymentOperationType.AUTHORIZE,
                PaymentOperationResult.SUCCEEDED,
                data.idempotency_key,
                amount_minor=payment.total_amount_minor,
                provider_reference=result.provider_reference,
            )
        self.session.flush()
        if on_commit is not None and payment.status is not PaymentStatus.AUTHORIZATION_FAILED:
            on_commit(self.session)
        return payment

    def capture(
        self, payment_id: UUID, data: PaymentCapture, *, on_commit: OnCommit = None
    ) -> Payment:
        return self._capture_durable(payment_id, data, on_commit=on_commit)

    def _capture_durable(
        self, payment_id: UUID, data: PaymentCapture, *, on_commit: OnCommit = None
    ) -> Payment:
        with self.session.begin():
            payment = self.payments.get_for_update(payment_id)
            if payment is None:
                raise _not_found("Payment")
            booking = self.bookings.get_for_update(payment.booking_id)
            if booking is None:
                raise _not_found("Booking")
            existing = self._replay_operation(
                data.idempotency_key, payment, PaymentOperationType.CAPTURE
            )
            unresolved = self.operations.get_any_unresolved(payment.id)
            if unresolved is not None and unresolved.idempotency_key != data.idempotency_key:
                return payment
            if existing is not None and existing.result in {
                PaymentOperationResult.SUCCEEDED,
                PaymentOperationResult.FAILED,
            }:
                return payment
            if booking.status is not BookingStatus.CONFIRMED:
                raise PaymentEligibilityError("Capture requires a confirmed booking")
            if existing is None:
                if not is_capturable(payment.status):
                    raise InvalidPaymentStateError(
                        "Payment cannot be captured in its current state"
                    )
                if (
                    payment.provider_payment_reference is None
                    or payment.authorized_amount_minor is None
                ):
                    raise InvalidPaymentStateError("Payment has no authorization to capture")
                existing = self._record(
                    payment,
                    PaymentOperationType.CAPTURE,
                    PaymentOperationResult.PENDING,
                    data.idempotency_key,
                    amount_minor=payment.authorized_amount_minor,
                    provider_reference=payment.provider_payment_reference,
                )
                existing.attempt_count = 0
            else:
                existing.result = PaymentOperationResult.PENDING
                existing.failure_code = None
            existing.attempt_count += 1
            self.session.flush()
            provider = self._provider_for(payment)
            provider_key = str(existing.correlation_id)
            provider_reference = payment.provider_payment_reference
            amount_minor = payment.authorized_amount_minor
            currency = payment.currency
            assert provider_reference is not None and amount_minor is not None

        try:
            result = provider.capture(
                provider_reference=provider_reference,
                amount_minor=amount_minor,
                currency=currency,
                idempotency_key=provider_key,
            )
        except PaymentProviderError:
            return self._mark_unknown(payment_id, data.idempotency_key)

        with self.session.begin():
            payment = self.payments.get_for_update(payment_id)
            operation = self.operations.get_by_idempotency_key(data.idempotency_key)
            assert payment is not None and operation is not None
            payment.provider_status = result.provider_status
            operation.provider_reference = result.provider_reference
            if payment.status is PaymentStatus.CAPTURED:
                operation.result = PaymentOperationResult.SUCCEEDED
                operation.failure_code = None
                return payment
            if result.outcome is ProviderOutcome.FAILED:
                payment.status = validate_payment_transition(
                    payment.status, PaymentStatus.CAPTURE_FAILED
                )
                operation.result = PaymentOperationResult.FAILED
                operation.failure_code = result.failure_code
            else:
                payment.status = validate_payment_transition(payment.status, PaymentStatus.CAPTURED)
                payment.captured_amount_minor = amount_minor
                payment.captured_at = _utc_now()
                operation.result = PaymentOperationResult.SUCCEEDED
                if result.provider_reference is not None:
                    payment.provider_payment_reference = result.provider_reference
            self.session.flush()
            if on_commit is not None and operation.result is PaymentOperationResult.SUCCEEDED:
                on_commit(self.session)
            return payment

    def _capture_locked(
        self,
        payment: Payment,
        booking: Booking,
        data: PaymentCapture,
        *,
        on_commit: OnCommit = None,
    ) -> Payment:
        if self._replay(data.idempotency_key, payment, PaymentOperationType.CAPTURE):
            return payment
        if booking.status is not BookingStatus.CONFIRMED:
            raise PaymentEligibilityError("Capture requires a confirmed booking")
        if not is_capturable(payment.status):
            raise InvalidPaymentStateError("Payment cannot be captured in its current state")
        if payment.provider_payment_reference is None or payment.authorized_amount_minor is None:
            raise InvalidPaymentStateError("Payment has no authorization to capture")

        result = self._provider_for(payment).capture(
            provider_reference=payment.provider_payment_reference,
            amount_minor=payment.authorized_amount_minor,
            currency=payment.currency,
            idempotency_key=data.idempotency_key,
        )
        payment.provider_status = result.provider_status
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
        if on_commit is not None and payment.status is not PaymentStatus.CAPTURE_FAILED:
            on_commit(self.session)
        return payment

    def void(self, payment_id: UUID, data: PaymentVoid, *, on_commit: OnCommit = None) -> Payment:
        return self._void_durable(payment_id, data, on_commit=on_commit)

    def _void_durable(
        self, payment_id: UUID, data: PaymentVoid, *, on_commit: OnCommit = None
    ) -> Payment:
        with self.session.begin():
            payment = self.payments.get_for_update(payment_id)
            if payment is None:
                raise _not_found("Payment")
            existing = self._replay_operation(
                data.idempotency_key, payment, PaymentOperationType.VOID
            )
            unresolved = self.operations.get_any_unresolved(payment.id)
            if unresolved is not None and unresolved.idempotency_key != data.idempotency_key:
                return payment
            if existing is not None and existing.result in {
                PaymentOperationResult.SUCCEEDED,
                PaymentOperationResult.FAILED,
            }:
                return payment
            if existing is None:
                if not is_voidable(payment.status):
                    raise InvalidPaymentStateError("Payment cannot be voided in its current state")
                existing = self._record(
                    payment,
                    PaymentOperationType.VOID,
                    PaymentOperationResult.PENDING,
                    data.idempotency_key,
                    amount_minor=payment.authorized_amount_minor or 0,
                    provider_reference=payment.provider_payment_reference,
                )
                existing.attempt_count = 0
            else:
                existing.result = PaymentOperationResult.PENDING
                existing.failure_code = None
            existing.attempt_count += 1
            self.session.flush()
            provider = self._provider_for(payment)
            provider_key = str(existing.correlation_id)
            provider_reference = payment.provider_payment_reference

        if provider_reference is not None:
            try:
                result = provider.void(
                    provider_reference=provider_reference, idempotency_key=provider_key
                )
            except PaymentProviderError:
                return self._mark_unknown(payment_id, data.idempotency_key)
        else:
            result = None

        with self.session.begin():
            payment = self.payments.get_for_update(payment_id)
            operation = self.operations.get_by_idempotency_key(data.idempotency_key)
            assert payment is not None and operation is not None
            if payment.status is PaymentStatus.CANCELLED:
                operation.result = PaymentOperationResult.SUCCEEDED
                operation.failure_code = None
                return payment
            if result is not None and result.outcome is ProviderOutcome.FAILED:
                operation.result = PaymentOperationResult.FAILED
                operation.failure_code = result.failure_code
                operation.provider_reference = result.provider_reference
                self.session.flush()
                return payment
            payment.status = validate_payment_transition(payment.status, PaymentStatus.CANCELLED)
            payment.cancelled_at = _utc_now()
            operation.result = PaymentOperationResult.SUCCEEDED
            if result is not None:
                payment.provider_status = result.provider_status
                operation.provider_reference = result.provider_reference
            self.session.flush()
            if on_commit is not None:
                on_commit(self.session)
            return payment

    def _mark_unknown(self, payment_id: UUID, idempotency_key: str) -> Payment:
        with self.session.begin():
            operation = self.operations.get_by_idempotency_key(idempotency_key)
            payment = self.payments.get_for_update(payment_id)
            assert operation is not None and payment is not None
            operation.result = PaymentOperationResult.UNKNOWN
            operation.failure_code = "provider_outcome_unknown"
            self.session.flush()
            return payment

    def _void_locked(
        self, payment: Payment, data: PaymentVoid, *, on_commit: OnCommit = None
    ) -> Payment:
        if self._replay(data.idempotency_key, payment, PaymentOperationType.VOID):
            return payment
        if not is_voidable(payment.status):
            raise InvalidPaymentStateError("Payment cannot be voided in its current state")

        provider_reference = payment.provider_payment_reference
        # A provider reference is the authoritative signal that a provider-side
        # authorization/intent still exists. CAPTURE_FAILED retains that reference,
        # so local cancellation must not be declared until provider void succeeds.
        if provider_reference is not None:
            result = self._provider_for(payment).void(
                provider_reference=provider_reference, idempotency_key=data.idempotency_key
            )
            provider_reference = result.provider_reference
            if result.outcome is ProviderOutcome.FAILED:
                self._record(
                    payment,
                    PaymentOperationType.VOID,
                    PaymentOperationResult.FAILED,
                    data.idempotency_key,
                    amount_minor=payment.authorized_amount_minor or 0,
                    provider_reference=provider_reference,
                    failure_code=result.failure_code,
                )
                self.session.flush()
                return payment

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
        if on_commit is not None:
            on_commit(self.session)
        return payment

    def orchestrate_booking_transition(self, booking: Booking, transition: str) -> Payment | None:
        """Apply a committed Booking transition through the durable command path."""
        with self.session.begin():
            payment = self.payments.get_by_booking(booking.id)
            if payment is None:
                return None
            payment_id = payment.id
            payment_status = payment.status
        key = f"booking:{booking.id}:{transition}"
        if transition == "confirm:capture":
            if payment_status in {PaymentStatus.AUTHORIZED, PaymentStatus.CAPTURE_FAILED}:
                return self.capture(payment_id, PaymentCapture(idempotency_key=key))
            return payment
        if transition in {"reject:void", "cancel:void"}:
            if is_voidable(payment_status):
                return self.void(payment_id, PaymentVoid(idempotency_key=key))
            return payment
        raise ValueError("Unsupported booking payment orchestration transition")

    def refund(
        self, payment_id: UUID, data: RefundCreate, *, on_commit: OnCommit = None
    ) -> PaymentOperation:
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

            result = self._provider_for(payment).refund(
                provider_reference=payment.provider_payment_reference or "",
                amount_minor=data.amount_minor,
                currency=payment.currency,
                idempotency_key=data.idempotency_key,
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
            if on_commit is not None:
                on_commit(self.session)
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

    def list_platform_exceptions(
        self,
        *,
        results: list[PaymentOperationResult],
        operation: PaymentOperationType | None,
        limit: int,
        offset: int,
    ) -> list[tuple[PaymentOperation, Payment]]:
        rows = self.operations.list_exceptions(
            results=results, operation=operation, limit=limit, offset=offset
        )
        return [(row, row.payment) for row in rows]

    def get_platform_detail(
        self, payment_id: UUID, *, limit: int, offset: int
    ) -> tuple[Payment, list[PaymentOperation]]:
        payment = self.get(payment_id)
        return payment, list(
            self.operations.list_for_payment(payment_id, limit=limit, offset=offset)
        )

    def reconcile_operation(self, operation_id: UUID, *, on_commit: OnCommit = None) -> Payment:
        """Retry one UNKNOWN durable attempt without minting new financial identity."""
        with self.session.begin():
            operation = self.operations.get_for_update(operation_id)
            if operation is None:
                raise _not_found("Payment operation")
            if operation.result is not PaymentOperationResult.UNKNOWN:
                raise InvalidPaymentStateError(
                    "Only an UNKNOWN payment operation can be reconciled manually"
                )
            payment_id = operation.payment_id
            operation_type = operation.operation
            idempotency_key = operation.idempotency_key
            # Claim this exact logical operation before provider dispatch. A concurrent
            # reviewer observes PENDING and fails closed; provider identity remains the
            # existing correlation_id inside the durable command implementation.
            operation.result = PaymentOperationResult.PENDING
            operation.failure_code = None
            self.session.flush()
        try:
            if operation_type is PaymentOperationType.AUTHORIZE:
                return self.authorize(
                    payment_id,
                    PaymentAuthorize(idempotency_key=idempotency_key),
                    on_commit=on_commit,
                )
            if operation_type is PaymentOperationType.CAPTURE:
                return self.capture(
                    payment_id,
                    PaymentCapture(idempotency_key=idempotency_key),
                    on_commit=on_commit,
                )
            if operation_type is PaymentOperationType.VOID:
                return self.void(
                    payment_id, PaymentVoid(idempotency_key=idempotency_key), on_commit=on_commit
                )
            raise InvalidPaymentStateError("This payment operation cannot be reconciled manually")
        except (InvalidPaymentStateError, PaymentEligibilityError):
            # The provider was not dispatched. Restore the factual unresolved state;
            # otherwise a local eligibility conflict would strand the attempt as if a
            # provider call were still in flight.
            with self.session.begin():
                claimed = self.operations.get_for_update(operation_id)
                if claimed is not None and claimed.result is PaymentOperationResult.PENDING:
                    claimed.result = PaymentOperationResult.UNKNOWN
                    claimed.failure_code = "provider_outcome_unknown"
            raise

    # -- Idempotency helpers ------------------------------------------------

    def _replay(
        self, idempotency_key: str, payment: Payment, operation: PaymentOperationType
    ) -> bool:
        return self._replay_operation(idempotency_key, payment, operation) is not None

    def _replay_operation(
        self, idempotency_key: str, payment: Payment, operation: PaymentOperationType
    ) -> PaymentOperation | None:
        self.operations.lock_idempotency_key(idempotency_key)
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
                provider_kind=payment.payment_provider,
                attempt_count=1,
            )
        )
