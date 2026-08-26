# Phase 9.6.B0 — Customer Payment Initiation Boundary

## Scope and base

Implemented from canonical base `c3834a453295b8495f1d41ef62ade4b6af1de972`.
The slice adds one authenticated command:

`POST /api/v1/bookings/{booking_id}/payment/initiate`

It closes the missing customer command boundary identified by the Phase 9.6
baseline audit. It does not add customer payment UI or real-money readiness.

## Authority and contract

The caller must have an authenticated session, a membership-validated active
CUSTOMER organization, ownership of the target Booking, and `payment.initiate`.
Cross-tenant targets use existing concealment semantics.

The request is closed to extra fields and contains only `idempotency_key`. The
server derives customer ownership, Booking eligibility, currency, total, allocation,
and provider. The response is the existing customer-safe payment status shape:
payment/booking IDs, status, currency, customer total, aggregate authorized/captured/
refunded values, customer-action flag, and safe lifecycle timestamps. It excludes
internal reference, provider fields, allocation, operations, idempotency data, failure
diagnostics, audit data, and secrets.

## Orchestration and concurrency

The command uses the existing Payment creation and provider-neutral authorization
logic inside one B0 transaction. It locks the Booking, resolves any existing Payment,
and validates the global operation key before creating a Payment, returning an
authoritative no-op state, or calling the provider. A key bound to another Payment or
operation therefore conflicts without leaving a new `CREATED` Payment. A compatible
same-Payment AUTHORIZE key replays safely; a genuinely unused fresh key may return an
already authorized, captured, refunded, or customer-action-required Payment without
another provider call. A failed authorization remains retryable with a new key and a
cancelled Payment fails closed.

Booking/Payment row locks and a transaction-scoped PostgreSQL advisory lock derived
from the supplied global key serialize competing commands before any provider action.
The one-Payment-per-Booking constraint, immutable Booking snapshot foreign key, and
global operation-key uniqueness remain final persistence backstops. Both B0 and the
existing financial commands use the same keyed lock plus compatibility lookup; this
closes cross-Payment preflight races rather than relying on a SELECT alone. The locked
Payment lookup retains `populate_existing=True` so a waiter sees the state committed
while it was blocked rather than a stale identity-map snapshot.
Durable pre-provider-call unknown-outcome recovery remains a later Stripe resilience
concern; this remediation does not claim to solve it.

## Provider and financial boundaries

B0 acceptance uses the deterministic FAKE provider only. Provider selection remains
server-side. Stripe remains disabled and no Stripe request, PaymentIntent, publishable
key, webhook exercise, or frontend dependency is introduced. Stripe financial
onboarding gates remain unchanged and still apply whenever server configuration selects
Stripe.

The command accepts no PAN, CVC, expiry, payment-method credential, amount, currency,
provider, customer/operator identity, status, capture, void, or refund authority. It
authorizes only. It never confirms a Booking, captures, voids, refunds, or mutates the
TripRequest or selected Offer. Existing platform create/authorize/capture/void/refund
routes retain their original permissions.

SCA representation remains compatible through the aggregate's
`requires_customer_action` field. Browser SCA completion and transient client-action
delivery are deferred; the fake provider does not manufacture SCA behavior.

## Inventory and validation

- Routes: `86 / 82 / 4` to `87 / 83 / 4`.
- Alembic remains `20260813_0009`; no migration `0010`.
- No Web proxy/client/UI change is included. Phase 9.6.A will design the browser seam.
- PostgreSQL tests cover ownership, role denial, request authority, exact response,
  create-or-reuse behavior, replay, same- and different-key concurrency,
  cross-Booking global-key collision, lifecycle invariants, and zero capture/refund.
- Existing Payment, Stripe adapter/webhook, financial onboarding, customer read, and
  platform-operation regression suites remain authoritative.

Phase 9.6.B will decide capture/reversal orchestration. Phase 9.6.C will address Stripe
browser/SCA behavior, provider failure simulation, and durable unknown-outcome recovery.
