# Phase 9.7.A1 — operator aircraft discovery

Phase 9.7.A1 is based on merge `b911d77684f155a8194a4fa286a73a3adebd823a`.
It supplies the narrow prerequisite that blocked the Phase 9.7.A operator Offer UI.
No Web UI, aircraft-management workflow, dependency, or database migration is added.

## Active-operator aircraft collection

`GET /api/v1/me/operator-aircraft` requires authentication, a validated active
OPERATOR organization, and canonical `operator.read`. All five operator roles have
that read permission. The operator is resolved from principal membership and active
organization; the route accepts no `operator_id`.

The response is a bounded page (`limit` defaults to 20, range 1–100; `offset >= 0`)
ordered by registration and UUID. Its dedicated projection contains only aircraft ID,
registration, manufacturer, model, category, passenger capacity, factual aircraft
status, and an `eligible` indicator. It excludes operator identity, compliance reasons
or evidence, reviewers, documents, customer/payment/provider data, and audit metadata.

The collection means owned aircraft plus a factual current eligibility signal. Operator
admission/evidence is evaluated once and aircraft authorizations are loaded in one batch.
The non-empty query count is fixed at five regardless of page size: admission, two
operator-evidence queries, bounded aircraft, and batched authorizations. The GET writes
nothing.

Eligibility is informational. Offer creation remains authoritative and independently
revalidates the TripRequest state, server-derived operator, aircraft ownership, operator
admission/evidence, and aircraft authorization under its existing locking transaction.
A stale collection therefore cannot authorize an Offer.

## Offer creation authority

`POST /api/v1/me/operator-offers` is the browser-safe active-operator command. Its
dedicated request schema has no `operator_id`; the router derives the owner exclusively
from the validated active organization, requires canonical `offer.manage`, and then
invokes the existing Offer lifecycle service. Unknown authority/commercial fields are
rejected, including operator/customer/organization identity, platform fee, customer
total, and payment/provider fields.

The existing `POST /api/v1/offers` trusted/platform contract remains compatible rather
than silently changing audience semantics. Both routes converge on the same transaction,
ownership/compliance checks, server-derived fee and total calculations, and existing
DRAFT/SUBMITTED/WITHDRAWN/SELECTED lifecycle. A foreign aircraft UUID cannot create an
Offer and does not transfer tenant authority.

## Locks and deferred work

The route inventory becomes 90 registered / 86 API/OpenAPI / 4 documentation. Alembic
remains `20260827_0010`; there is no `0011`. Phase 9.7.A may restart using this exact
aircraft collection and the operator-scoped Offer command. Aircraft picker/editor UI,
broader aircraft management, booking history,
payments, refunds, realtime behavior, Phase 9.7.B, and Phase 9.8 remain deferred.
