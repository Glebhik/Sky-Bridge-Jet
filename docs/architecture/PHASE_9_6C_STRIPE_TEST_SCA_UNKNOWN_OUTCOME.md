# Phase 9.6.C — Stripe test-mode, SCA, and unknown-outcome hardening

## Identity and boundary

This implementation is based on canonical commit
`825ae00086c3af78affa84b17b8b97387b8793a8`. It activates no live provider and
makes no real-money transaction. Server configuration continues to reject live
Stripe secret keys while `STRIPE_TEST_MODE_REQUIRED=true`; the browser separately
accepts only a `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` beginning with `pk_test_` and
otherwise renders a fail-closed unavailable state.

The official, pinned browser dependencies are `@stripe/stripe-js@9.14.0` and
`@stripe/react-stripe-js@6.8.2`. The existing official Python Stripe SDK remains
the server adapter dependency. Stripe.js is the intentional external browser asset
boundary. No CSP was weakened or broadened in this phase.

## PCI and customer UI

Card number, expiry, and security code are entered only in Stripe-hosted Payment
Element fields. Sky Bridge Jet creates no raw card inputs and does not receive,
persist, proxy, or log those values. The customer explicitly starts authorization,
then explicitly confirms the hosted element. The UI states that authorization is
not capture and keeps provider success distinct from Booking confirmation.

The publishable key is browser-visible by design and is not a secret. Stripe secret
and webhook-signing keys remain server-only. A PaymentIntent client secret is
sensitive browser-required capability data: it exists only in the initiation
command response, React memory, and the mounted Elements provider. It is excluded
from all customer Payment reads, durable models, storage, URLs, analytics, and logs;
it is cleared after completion, organization/identity change, or unmount. Reload
therefore requires an authoritative status read and, only while still unresolved, a
same-logical-attempt retry that reuses the server-side provider identity.

## PaymentIntent and SCA contract

Stripe authorization creates a manual-capture PaymentIntent with automatic payment
methods enabled. With no pre-existing payment method it remains
`requires_payment_method` and returns a transient `stripe_confirm_payment` action;
`requires_action` uses the same action contract for 3-D Secure/SCA. Stripe.js calls
`confirmPayment` with `redirect: "if_required"`. A verified webhook, not the browser,
is authoritative for the final financial transition. Failure or abandonment leaves
the Payment factual and retryable and never implies authorization, capture, Booking
confirmation, or ticketing.

## Durable operation and unknown-outcome model

Migration `20260827_0010` extends the existing `payment_operations` ledger with:

- `PENDING` and `UNKNOWN` results;
- immutable globally unique `correlation_id`;
- pinned `provider_kind`;
- `attempt_count` and `updated_at`.

Before AUTHORIZE, CAPTURE, or VOID calls the service locks the aggregate, validates
eligibility, creates or reuses one logical operation, and commits that reservation.
The provider call occurs outside the database transaction. Finalization then locks
and reconciles the same Payment and operation. A transport/provider infrastructure
error changes only the operation to `UNKNOWN` with a safe failure category; it does
not invent a failed financial outcome or regress Payment/Booking state.

Every retry of one logical operation derives the provider idempotency key from the
durable operation correlation UUID. Customer request keys are never forwarded as
provider identity. Attempt count increments per dispatch, while correlation and
provider idempotency remain stable across process/session boundaries. An unresolved
operation prevents a different key or a competing capture/void command from creating
a second logical provider action. Database row/advisory locks and the global unique
request-key constraint close same-Payment and cross-Payment races.

Fake-provider references are deterministic from the provider key, so local tests
exercise the same identity invariant without network access. Stripe metadata is
limited to opaque `operation_correlation`; it contains no customer, passenger,
Booking, trip, price-detail, email, or organization data.

## Recovery and webhooks

A provider response may be lost after success. AUTHORIZE, CAPTURE, and VOID can then
be retried with the same durable correlation, allowing Stripe idempotency to return
the original logical result rather than perform a second action. If a webhook wins
the race, its verified `operation_correlation` locates the operation even when the
PaymentIntent reference was never received synchronously. Reconciliation may then
recover that reference and complete only the matching PENDING/UNKNOWN operation.

Webhook event uniqueness preserves duplicate idempotency. Domain transition guards
prevent out-of-order capture, cross-Payment mutation, and provider-authoritative
capture of an unconfirmed Booking. `payment_intent.canceled` is mapped to the
pre-capture cancellation/void state. Captured cancellation still triggers no
automatic refund; refund remains explicitly outside Phase 9.6.C.

Before any webhook-driven financial mutation, four pieces of evidence must agree:
the normalized provider event, the resolved Payment, ownership of the supplied
operation correlation, and the correlated `PaymentOperation.operation` type. A
provider reference and correlation that resolve to different Payments fail closed.
So does a correlation whose operation type is incompatible with the event, before
binding a provider reference or changing Payment, Booking, amounts, customer-action
state, or the operation ledger. The canonical mapping is:

- `AUTHORIZED` and `AUTHORIZATION_FAILED` → `AUTHORIZE`;
- `CAPTURED` → `CAPTURE`;
- `CANCELLED` → `VOID`.

Financial branches are event-exact: capture semantics execute only for `CAPTURED`,
and cancellation/void semantics only for `CANCELLED`; local Payment state alone
cannot select an operation. These invariants were added after independent
adversarial audit found and reproduced three fail-closed defects: a cross-Payment
reference/correlation mismatch, `CANCELLED` entering the capture branch, and a
same-Payment correlation whose operation type disagreed with its provider event.
Durable service-level and locally signed fake-webhook tests cover all repairs. They
are not evidence of an external Stripe network or real-provider test.

## Compatibility, routes, and evidence

No new API route is introduced. The closed customer proxy and
`portalApi.initiatePayment` continue to use the existing owned-Booking initiation
route; only that command response gains optional transient `client_action`. Existing
read projections, FAKE-provider flows, capture/void orchestration, multi-organization
ownership, and SALES read-only boundaries remain intact.

The expected inventory remains 87 total routes: 83 API and 4 non-API. Alembic head
becomes `20260827_0010`; upgrade and model-drift checks are mandatory. Local evidence
uses only the deterministic FAKE provider, mocked Stripe gateway/SDK seams, signed
local webhook fixtures, hosted-element mocks, and disposable PostgreSQL. Tests cover
SCA, missing/live publishable-key fail-closed behavior, transient secrets, global
idempotency collisions, capture/void exclusion, lost-response retry for all three
commands, provider-reference recovery, duplicate/out-of-order webhook delivery, and
full API/Web regression.

## Remaining production-readiness gaps

Before production, infrastructure must supply separately managed Stripe test/live
configuration through an approved secrets system, deploy an explicit reviewed CSP
for Stripe.js/Elements if the platform adopts one, add operational reconciliation
workers/alerts and aged-UNKNOWN handling, validate real test-mode 3DS cards in a
separately authorized environment, and complete compliance/PCI and provider account
reviews. Live-mode activation, real external Stripe calls in this task, real-money
acceptance, automated refunding, and Phase 9.7 are expressly excluded.
