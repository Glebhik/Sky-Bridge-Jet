# Sky Bridge Jet V1 Architecture and Implementation Plan

## Purpose and scope

Sky Bridge Jet is a premium, discreet private aviation marketplace, initially
for Europe. It connects customers, their delegates, and concierge companies
with private jet operators and brokers. It is not a retail airline search
engine or generic travel site.

This document records the Phase 0 audit and a recommendation for V1. It is an
implementation guide, not evidence of legal, regulatory, or security
compliance. Qualified counsel and relevant specialists must validate those
areas before production operation.

## Repository audit and existing-state assessment

Audit date: 2026-08-10.

| Area | Finding |
| --- | --- |
| Repository structure | Root-only repository |
| Source code | None |
| Technology or dependencies | None declared |
| Configuration | None |
| CI/CD | None |
| Tests | None |
| Documentation | A one-line root README before this audit |
| Git history | One `Initial commit` on `main` |
| Existing architecture decisions | None recorded |

The repository is deliberately at a pre-implementation state. The original
README was preserved and clarified. No application, infrastructure, dependency,
or generated files were added in Phase 0.

## Recommended V1 architecture

Use a modular monolith, deployed as a web application and API, rather than
microservices. Private aviation workflows will change as operator onboarding
and the commercial model mature; a modular monolith keeps transactions,
authorization, and audit trails coherent while allowing bounded contexts and
provider adapters to be extracted later if justified by operational needs.

The core API owns domain rules, state transitions, authorization decisions, and
an immutable business audit trail. It exposes a versioned HTTP API to the web
application. Background work handles notifications, provider polling, document
processing, and other retryable integration jobs; it must not bypass domain
state-transition rules.

Core business modules must depend only on ports they own. Concrete operator,
airport, payment, identity, mapping, notification, and AI implementations
belong in adapter modules. This prevents any vendor API from shaping the core
domain or making a later replacement expensive.

Store money as integer minor units plus ISO 4217 currency, or a fixed-precision
database decimal where a currency requires it; never use binary floating point.
Use UUID primary identifiers and UTC, timezone-aware timestamps. Preserve the
requesting customer's local time zone and the airport time zone as explicit
business data where relevant.

## Recommended technology stack

| Area | Recommendation | Evaluation |
| --- | --- | --- |
| Web | Next.js, React, TypeScript | Appropriate for a premium responsive customer and operations UI, SSR where useful, and a mature TypeScript ecosystem. Keep business rules in the API. |
| API | Python 3.12+ and FastAPI | Appropriate for typed HTTP APIs, async integration boundaries, and a future AI parsing layer. Use explicit service and domain layers rather than route-centric business logic. |
| Database | PostgreSQL | Appropriate for transactional bookings, constraints, JSON integration payloads, full-text needs, and reliable migrations. |
| ORM | SQLAlchemy 2.x | Appropriate for explicit mappings, transactions, and avoiding a provider-specific persistence layer. |
| Migrations | Alembic | Appropriate companion to SQLAlchemy; migrations must be reviewable and forward-only in deployed environments. |
| Backend tests | pytest | Appropriate for domain, integration, and API tests; use factories and a disposable PostgreSQL database. |
| Frontend tests | TypeScript unit/component test runner | Appropriate for component behavior; select Vitest and React Testing Library during Phase 1 for fast, ecosystem-aligned coverage. |
| End-to-end tests | Playwright | Appropriate for critical customer and operations workflows across supported browsers. |
| Local infrastructure | Docker and Docker Compose | Appropriate for reproducible local PostgreSQL, API, web, and later worker environments. Do not require Docker for every unit test. |
| CI | GitHub Actions | Appropriate for the repository host and initial scale: quality checks, tests, build, migration verification, and dependency/security scanning. |

The alternatives do not warrant a change now. A JVM or Node API would be
viable, but Python is the better fit for the stated FastAPI and future
AI-assisted intent-parsing direction. Microservices, Kubernetes, event
streaming platforms, and a separate BFF are premature for V1.

## Proposed repository structure

```text
sky-bridge-jet/
├── apps/
│   ├── api/                    # FastAPI modular monolith
│   │   ├── src/sky_bridge_jet/
│   │   │   ├── modules/        # Bounded contexts and their application/domain layers
│   │   │   ├── adapters/       # Provider implementations
│   │   │   ├── shared/         # Small cross-cutting primitives only
│   │   │   └── main.py
│   │   ├── alembic/
│   │   └── tests/
│   └── web/                    # Next.js application
│       ├── src/
│       └── tests/
├── packages/
│   ├── api-contracts/          # Generated/versioned API client and schemas
│   └── ui/                     # Shared visual primitives, not business logic
├── docs/
│   ├── architecture/
│   ├── product/
│   ├── api/
│   ├── security/
│   └── decisions/
├── infra/                      # Container and deployment definitions
├── tests/
│   └── e2e/                    # Playwright critical-path suites
├── .github/workflows/
├── docker-compose.yml
├── .env.example
├── Makefile
└── README.md
```

`packages/api-contracts` is preferable to a broad shared-types package: the
client and server exchange explicit API contracts, while Python domain models
and TypeScript UI models remain independently owned. Add only the packages
needed in Phase 1.

## Domain boundaries

| Bounded context | Responsibility |
| --- | --- |
| Identity and Access | Authentication, roles (`CUSTOMER`, `OPERATOR`, `ADMIN`, `CONCIERGE`), organization/delegated access, sessions, and authorization policy. |
| Customer | Customer profiles, preferences, privacy choices, and relationship to delegates or concierge organizations. |
| Passenger | Passenger identity and travel details, with minimized and protected PII. |
| Airport | Airport, FBO, operational metadata, and airport-search normalization. |
| Operator | Operator/broker organizations, onboarding state, operating capabilities, and operator users. |
| Aircraft | Aircraft records, categories, capability metadata, and operator association. |
| Trip Request | A customer request and one or more legs, passengers, pets, baggage, catering, transfers, and lifecycle from draft through cancelled/expired. |
| Quote | Operator offers, validity, release/withdrawal, selection, and immutable commercial snapshots. |
| Pricing | Currency-safe calculations, fees, tax inputs, price breakdowns, and approval of commercial amounts. |
| Booking | Booking lifecycle, confirmations, passengers, terms acceptance, and completion/cancellation/refund coordination. |
| Empty Legs | First-class repositioning opportunities, availability constraints, publication state, and conversion to a trip/booking flow. |
| Payment | Payment intent/status reconciliation and provider references; payment card data must remain with a compliant payment provider. |
| Notification | Templated, consent-aware, reliable messages and delivery records. |
| Concierge and AI | Structured draft extraction, unresolved questions, human/customer confirmation, and concierge workflow. |
| Audit | Append-only actor/action/time/context records for sensitive business and administrative events. |

The Trip Request, Quote, and Booking state machines are separate. Enforce their
allowed transitions in domain services, not UI code. Quote selection must
create a durable commercial snapshot before a booking is confirmed. Empty legs
may feed a trip request or booking flow but retain their own origin and
availability lifecycle.

## Provider-adapter architecture

Each core-owned port has a stable request/response model, capability metadata,
timeout/retry policy, normalized errors, correlation identifiers, and an
adapter-specific audit record. Provider credentials, raw payloads containing
personal data, and vendor SDK types must not leak into core domain objects.

| Core port | Adapter responsibility |
| --- | --- |
| `AirportDataProvider` | Airport/FBO lookup, normalization, and data refresh |
| `AircraftAvailabilityProvider` | Available aircraft and operational constraints |
| `OperatorQuoteProvider` | Quote request dispatch, quote ingestion, and status updates |
| `PaymentProvider` | Hosted/tokenized payment initiation, webhooks, and reconciliation |
| `IdentityVerificationProvider` | Identity/KYC checks only where the approved product flow requires them |
| `NotificationProvider` | Email/SMS/other delivery behind consent and template controls |
| `TripIntentParser` | Natural-language extraction to a validated Trip Request draft and unresolved questions |
| `MapProvider` | Geocoding, distance, and transfer-related mapping data |

Phase 1 should supply no live commercial adapters. Define ports, fake adapters,
and contract tests only when a module needs them. Webhook endpoints must verify
signatures, deduplicate events, and treat incoming data as untrusted.

## Security, privacy, and auditability

- Apply least privilege and deny-by-default authorization at API boundaries and
  in domain use cases; tenant and delegated-concierge access require explicit
  tests.
- Keep customer, passenger, payment, identity, and travel data classified and
  minimized. Encrypt data in transit and at rest, protect secrets in a managed
  secret store, and prohibit secrets from logs, test fixtures, and commits.
- Design for European privacy obligations: a data inventory, purpose and
  retention schedule, data-subject request process, processor/subprocessor
  records, consent/preference handling where applicable, and data-transfer
  assessment. Obtain legal advice before asserting GDPR or other compliance.
- Treat detailed travel plans and high-net-worth passenger information as
  sensitive operational data. Audit reads and exports where proportionate, use
  strict support access, and redact PII from observability data.
- Use a PCI-aligned payment-provider integration so card data does not pass
  through Sky Bridge Jet systems. Obtain specialist confirmation of the actual
  scope.
- Require MFA for administrative and operator roles, secure session management,
  rate limiting, abuse monitoring, dependency scanning, and a vulnerability
  response process.
- Produce append-only audit events for security-sensitive and commercial
  transitions, recording actor, authority, timestamp, correlation ID, and
  before/after references without duplicating unnecessary PII.
- AI output is untrusted input: validate it, show uncertainty, preserve user
  confirmation, and never allow it to autonomously confirm bookings or
  financial transactions.

## Major risks

### Technical risks

| Risk | Mitigation |
| --- | --- |
| Operator data/API inconsistency or absence | Normalize behind ports, keep provenance, support manual operator workflows, and avoid assuming real-time availability. |
| Complex concurrent quote/booking changes | Explicit state machines, quote expiry, idempotency keys, transactional locks where needed, and audit events. |
| Sensitive PII and travel-intelligence exposure | Data minimization, access controls, redaction, retention rules, and security review before production. |
| Payment/webhook duplication or loss | Idempotent webhook processing, reconciliation, and durable provider event records. |
| Premature distributed architecture | Begin as modular monolith with measurable extraction criteria. |
| AI extraction error or hallucination | Schema validation, clarification questions, provenance, and user review before submission. |

### Product risks

| Risk | Mitigation |
| --- | --- |
| Supply liquidity is insufficient for customer expectations | Validate operator acquisition and service-level model before promising instant booking. |
| Ambiguous marketplace role and commercial model | Owner decision on broker/marketplace position, fees, and contractual responsibilities. |
| Customers expect airline-like instant confirmation | Clearly communicate request, quote, validity, and confirmation stages. |
| Empty legs have volatile availability | Present availability and restrictions transparently; do not market them as guaranteed inventory. |
| Premium trust is undermined by a poor concierge experience | Test tone, delegation, exception handling, and human escalation with target users. |

## Phased roadmap and acceptance criteria

| Phase | Scope | Acceptance criteria |
| --- | --- | --- |
| 1. Engineering foundation | Create the approved repository structure, local environment, CI, baseline security controls, architecture decision records, and test harnesses. | Web and API build locally; PostgreSQL migrations run on a clean database; CI runs formatting, type/quality checks, unit tests, and builds; no live provider credentials or integrations. |
| 2. Core private aviation domain | Implement identity/access baseline, customer, passenger, airport, operator, aircraft, and Trip Request drafts/lifecycle. | Authorized users can create, validate, view, and cancel appropriate trip-request states; UUID, money, timezone, authorization, and audit conventions are tested. |
| 3. Quote, pricing, and booking lifecycle | Implement quote intake/selection, commercial snapshots, pricing, booking state machine, and payment-provider boundary. | Valid transitions, expiry, idempotency, audit records, and non-floating financial values are covered by tests; no booking becomes confirmed without required authorization. |
| 4. Customer experience | Deliver accessible responsive request, clarification, quote comparison, selection, booking-status, and passenger-management flows. | Critical customer journey passes Playwright coverage and is usable on supported mobile and desktop breakpoints. |
| 5. Operator and admin experience | Deliver operator quote management plus constrained administrative oversight, support, and audit access. | Operator and admin access is role-scoped; operators cannot access another operator's data; key administrative actions are audited. |
| 6. Empty Legs | Introduce first-class empty-leg inventory, search/discovery, qualification, and conversion flow. | Empty legs retain provenance and constraints, can expire/withdraw, and do not bypass quote/booking controls. |
| 7. AI Concierge | Add vendor-neutral intent parsing to create only a reviewable Trip Request draft. | Parser returns structured fields, confidence/unresolved questions, and provenance; a user or authorized concierge confirms all consequential actions. |
| 8. Security, testing, observability, and production hardening | Complete operational controls, backups/recovery, monitoring, alerting, performance work, privacy processes, and release readiness. | Documented threat model and incident process; monitored critical journeys; restore drill and load/security testing meet owner-approved targets; production approval occurs only after specialist reviews. |

## Decisions requiring owner approval

### A. Product-owner decisions

1. Marketplace role and operator commercial model: broker, marketplace, or
   another legal/commercial arrangement; fee payer and fee structure.
2. V1 service promise: request-for-quote only versus any instant-confirmation
   claim; operating hours and human concierge escalation.
3. Initial countries, customer/operator onboarding criteria, and launch
   geography within Europe.
4. Required identity/KYC, sanctions, payment, cancellation, refund, tax, and
   contractual policies following legal and finance advice.
5. Which V1 ancillary services are customer-visible: pets, catering, baggage,
   ground transfers, and concierge fulfillment.
6. Whether Empty Legs are in the initial commercial release or follow after
   core quote/booking validation.
7. Data retention, privacy notice, customer-consent model, and approved
   processors/subprocessors after qualified review.
8. AI Concierge launch scope, approved vendor posture, human review policy,
   and customer disclosure.

### B. Reversible engineering decisions

These can be made during implementation and documented in ADRs without
blocking Phase 1: package manager selection, exact test-runner configuration,
CSS/component-library choice, task queue library, logging vendor, deployment
provider, and individual adapter SDKs. The team may also select an initial
authentication implementation provided it meets the approved security
requirements and preserves the Identity and Access boundary.

## V1 Definition of Done

V1 is done only when the owner-approved European scope provides an accessible,
responsive experience for an authorized customer or delegate to submit a
private-flight request, receive and compare valid operator-originated quotes,
select an offer, complete the approved payment/status process, and view a
traceable booking lifecycle. Authorized operators and administrators must have
the minimum necessary workflows; all sensitive actions and commercial state
changes must be auditable.

It also requires tested authorization and tenant isolation, currency-safe
pricing, documented operational support and exception paths, reliable
notifications, critical-path automated tests, monitored production deployment,
backup/recovery procedures, and completion of owner-approved legal, privacy,
security, payment, and operational readiness reviews. It does not mean that
every future provider or region is supported.

## Explicit V1 non-goals

- Worldwide live operator coverage or a global launch
- Aircraft dispatch, crew scheduling, or flight operations control
- Aviation regulatory certification or claims of compliance without specialist review
- Complex worldwide taxation, escrow, or custody of funds
- Fractional ownership, jet cards, loyalty programs, or cryptocurrency
- Native mobile applications
- Global real-time aircraft tracking
- Autonomous AI bookings, payments, or irreversible commercial decisions
- A fully automated marketplace that removes the need for operator confirmation

## Implementation assumptions

The phased plan assumes a web-first Europe launch, request/quote/booking
workflow, and initially limited operator integrations with a manual fallback.
Every assumption that changes customer promises, legal obligations, financial
flows, or the marketplace role must receive owner approval before it shapes
implementation.
