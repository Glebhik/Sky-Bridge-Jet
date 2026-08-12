# ADR-031: Stripe Connect adapter behind the provider-neutral port (test mode, fail-closed)

## Status

Accepted — production PSP contracting, live-mode enablement, and Merchant-of-Record
classification deferred to specialist review (see ADR-025, ADR-035)

## Context

Phase 5 established a provider-neutral `PaymentProvider` port with a deterministic
`FakePaymentProvider` (ADR-025). Phase 7 connects that port to a **real** Stripe
Connect architecture, but must move no real money: Sky Bridge Jet operates in
Stripe **test mode only** in this phase, and the system must *enforce* — not merely
document — that constraint.

## Decision

Stripe is an **adapter, not the domain**. A `StripeConnectPaymentProvider`
implements the existing port (`authorize`/`capture`/`void`/`refund`) and maps
normalized Stripe results to provider-neutral outcomes; the `FakePaymentProvider`
remains and stays the default. A thin, injectable `StripeGateway` seam
(`core/stripe_gateway.py`) wraps the official pinned SDK so tests run against a fake
boundary with no network or credentials, and so no raw Stripe object or exception
ever crosses into the domain or the API. All SDK exceptions are converted to a
typed `PaymentProviderError` with a stable `ProviderErrorCategory`
(`PROVIDER_UNAVAILABLE` / `DECLINED` / `REQUIRES_ACTION` / `INVALID_STATE` /
`CONFIGURATION_ERROR` / `AUTHENTICATION_ERROR`); the API renders a fixed safe
message so no provider text (which could echo a key) leaks.

Test-mode enforcement is **fail-closed** in typed settings: when Stripe is enabled,
a secret key and webhook secret are required, and a live secret key
(`sk_live_` / `rk_live_`) is rejected while `STRIPE_TEST_MODE_REQUIRED` is set. The
key itself is never echoed in the error, logged, or returned. `STRIPE_ENABLED`
defaults to `false`, so the application boots and the full test suite runs with no
Stripe configuration and no silent fallback to the fake when Stripe is requested.

Each payment pins its `payment_provider` kind at creation, so authorize/capture/
refund always route to the provider that created the intent even if global
configuration changes.

## Consequences

A future Adyen (or other) adapter, and live-mode enablement, can be introduced
behind the same port without touching the payment domain. CI needs no Stripe
network access or credentials. The live-mode charge model, Merchant-of-Record,
statement descriptor, and PSD2/SCA legal obligations remain explicit
specialist-review gates (ADR-035); the software does not assert they are solved.
