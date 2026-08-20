# Sky Bridge Jet

Sky Bridge Jet is a premium private aviation marketplace and charter intermediary.
It is a managed marketplace: licensed operators remain responsible for flight
operation and execution.

## Phase 8 status

This repository contains the Phase 1 engineering foundation, the Phase 2 core
private-aviation backend domain, the Phase 3 quotes and operator offers domain,
the Phase 4 booking and reservation orchestration domain, the Phase 5 payment and
settlement core, the Phase 6 operator compliance and marketplace admission domain,
the Phase 7 production-payments and operator financial-onboarding integration, and
the Phase 8 identity, access, and organizations domain.
It provides a modular-monolith API shell, a responsive Next.js shell, local
PostgreSQL, migrations, test harnesses, and pull-request CI. Phase 2 adds the core
aviation domain. Phase 3 adds OperatorOffer. Phase 4 adds Booking. Phase 5 adds
Payment (provider-neutral, no real money moves). Phase 6 adds marketplace
admission, gating offer creation and booking confirmation on current
operator/aircraft eligibility.

Phase 7 connects the provider-neutral payment core to a **real Stripe Connect
architecture in Stripe TEST MODE ONLY** (no real money moves). Stripe is an
adapter behind the existing port — the `FakePaymentProvider` remains the default,
and test mode is *enforced* fail-closed (a live key is rejected). It adds a
separate **operator financial-onboarding** domain (`OperatorConnectedAccount`,
distinct from Phase 6 aviation compliance) that records provider-reported
capability state only, a financial eligibility gate for PSP-backed payments,
provider-neutral SCA (`requires_customer_action`) support, and a verified,
idempotent, data-minimized webhook pipeline. See
[the Phase 7 guide](docs/architecture/PHASE_7_PRODUCTION_PAYMENTS_OPERATOR_FINANCIAL_ONBOARDING.md).

Phase 7 deliberately does **not** implement live-mode payments, real money
movement, transfers/payouts (no scheduler; the Phase 5 allocation stays
authoritative), Merchant-of-Record, disputes/chargebacks, a tax/VAT engine, or an
independent KYC/KYB/AML/PEP/sanctions engine — the provider owns financial
identity checks, and the platform stores no bank/identity/beneficial-owner data.
Phase 8 makes authentication and authorization real application boundaries:
opaque-ID `User` identities (Argon2id passwords, server-side hashed sessions,
HttpOnly/SameSite cookies, CSRF, email verification and password reset),
`Organization`/`OrganizationMembership` (customer/operator/platform, linked by
reference to the existing Customer/Operator aggregates without rewriting them), a
centralized RBAC + resource-scope authorization policy, and a fail-closed global
API gate that classifies every route (compliance review and financial/refund
actions are now bound to authenticated platform principals — an operator can never
approve its own admission). A one-time CLI bootstraps the first product owner; no
credentials are committed. See
[the Phase 8 guide](docs/architecture/PHASE_8_IDENTITY_ACCESS_ORGANIZATIONS.md).

Phase 8 deliberately does **not** implement passkeys/WebAuthn or MFA (architected-
for future boundaries), real email delivery (deferred to the Notification phase),
or an external identity provider. Carried forward from prior phases, it also does
**not** implement automated government/regulator verification (EASA/FAA/CAA),
route-legality/traffic-rights/cabotage engines, real document storage or identity
verification, wallets/custody, invoices, an accounting ledger, Empty Legs, portals,
notifications, dispatch, crew, flight operations, FX, or AI. Legal, PSD2/payments,
tax, and aviation classifications are documented as specialist-review gates, not
solved in software.

## Architecture

- **Web:** Next.js 16.3.0, React 19.2.8, TypeScript, App Router.
- **API:** Python 3.12+, FastAPI, Pydantic Settings, and synchronous
  SQLAlchemy 2.x.
- **Database:** PostgreSQL 17 with Alembic.
- **Monorepo tooling:** pnpm 11.21.0 manages the JavaScript workspace; uv
  0.12.3 locks and installs Python dependencies.

The API uses synchronous SQLAlchemy consistently. Its request routes execute in
FastAPI's sync thread pool, while Alembic and request-scoped sessions share one
simple, explicit persistence model. Do not mix async SQLAlchemy into this
foundation.

Shared UI and type packages are intentionally deferred: no shared package has
immediate Phase 1 value, and API contracts should be added only when a real
cross-boundary contract exists.

```text
.
├── apps/
│   ├── api/                  # FastAPI modular monolith and Alembic
│   └── web/                  # Next.js App Router shell
├── docs/
│   ├── architecture/         # Approved implementation plan
│   ├── decisions/            # ADRs
│   └── product/              # Product vision
├── tests/e2e/                # Playwright smoke tests
├── .github/workflows/ci.yml  # Pull-request validation
├── docker-compose.yml
└── Makefile
```

## Prerequisites

- Node.js 22+ with Corepack
- pnpm 11.21.0 (Corepack installs the pinned version)
- Python 3.12+ and uv 0.12.3+
- Docker Desktop with Docker Compose for local PostgreSQL and containers

## Local setup

1. Copy the development examples into the repository root: `cp .env.example .env`.
2. Install dependencies and Playwright Chromium: `make setup`.
3. Start PostgreSQL: `docker compose up -d db`.
4. Apply migrations: `make migrate`.
5. Load the small deterministic development/demo airport set: `make seed-airports`.
6. Run the API: `make dev-api`.
7. Run the web shell in another terminal: `make dev-web`.

The web app runs at <http://localhost:3000>; the API runs at
<http://localhost:8000>. The browser talks only to the web app's own origin and the
Next.js server proxies API calls from `/api/proxy/*` to the upstream API. That upstream
origin is the **server-only** `API_UPSTREAM_ORIGIN` — it is read on the server, never
prefixed `NEXT_PUBLIC_*`, and never reaches the browser bundle. For host development it
defaults to `http://localhost:8000` (where `make dev-api` runs), so no configuration is
needed.

Alternatively, run the dev-focused container stack with `make dev`. The Compose API
connects to the `db` service and the web service is available on port 3000. Inside the
Compose network the API is reachable as the `api` service, not the web container's own
localhost, so the web service sets `API_UPSTREAM_ORIGIN=http://api:8000` automatically
(override with `WEB_API_UPSTREAM_ORIGIN` if needed); no browser-visible API-origin
variable is required. After the stack is healthy, apply migrations inside the API image
with `make migrate-compose`, then load seed data with `make seed-airports-compose`.

In production, deployment must explicitly set the server-only `API_UPSTREAM_ORIGIN` to the
API's origin. Use HTTPS whenever that connection crosses a host or untrusted network
boundary; plain HTTP is acceptable only for a controlled private container/network hop
such as `http://api:8000`. Never expose this value through a `NEXT_PUBLIC_*` variable.

The values in `.env.example` are development examples only. The API, Alembic,
and host-based Make targets read this repository-root `.env`. Docker Compose
also reads it for variable interpolation, then sets `DATABASE_HOST=db` inside
the API container. Do not commit a real `.env` or any credentials.

## Database and migrations

`DATABASE_URL` may be supplied directly and takes precedence when non-empty.
Otherwise the API builds it safely from
`DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD`, `DATABASE_HOST`, and
`DATABASE_PORT`. Keep `DATABASE_HOST=localhost` for host commands; Compose
uses `db` internally. Production configuration requires either an explicit
database URL or non-default component values, and rejects the checked-in
development password and localhost host.

Run existing migrations with:

```sh
make migrate
```

After adding a real SQLAlchemy model to a Phase 2 domain module, create a
reviewable migration with:

```sh
cd apps/api
uv run alembic revision --autogenerate -m "describe the schema change"
uv run alembic upgrade head
```

Alembic imports every `models.py` under
`sky_bridge_jet.modules.<bounded_context>` before inspecting
`sky_bridge_jet.db.base.Base.metadata`. Future bounded contexts must keep ORM
mappings in that convention; no domain module exists in Phase 1. The baseline
migration intentionally contains no business schema. The Phase 2 core aviation
module follows this convention.

Phase 2's migration creates the core aviation schema. Apply it with `make
migrate`, then load only the deterministic development/demo airports with
`make seed-airports`. The seed is idempotent and is not a complete production
airport data source.

## Quality commands

```sh
make test          # API pytest and web Vitest suites
make test-e2e      # Playwright Chromium smoke test (installed by make setup)
make lint          # Ruff, mypy, ESLint, TypeScript
make format        # Ruff and Prettier format checks
make format-write  # Apply Ruff and Prettier formatting
make build         # Next.js production build
make docker-config # Validate Docker Compose configuration
```

Run `make setup-e2e` to install Chromium separately when dependencies are
already installed. Run `make test-api-integration` with PostgreSQL available to
include the real readiness integration test.

Container runtime and tool base images are pinned to resolved immutable digests,
while application dependencies are pinned in committed pnpm and uv lockfiles.

Platform endpoints:

- `GET /health` returns `{"status":"ok"}` without a database dependency.
- `GET /ready` checks PostgreSQL with `SELECT 1`; it returns HTTP 503 and a
  non-sensitive unavailable status when PostgreSQL cannot be reached.
- `GET /api/v1` establishes the versioned API namespace.
- Phase 2 business resources and commands are exposed below `/api/v1`; see
  [the core domain guide](docs/architecture/PHASE_2_CORE_DOMAIN.md).
- Phase 3 operator offers and customer selection are exposed below `/api/v1`;
  see [the quotes and operator offers guide](docs/architecture/PHASE_3_QUOTES_OPERATOR_OFFERS.md).
- Phase 4 bookings and operator confirmation are exposed below `/api/v1`; see
  [the booking orchestration guide](docs/architecture/PHASE_4_BOOKING_RESERVATION_ORCHESTRATION.md).
- Phase 5 payments (authorize, capture, void, refund, allocation) are exposed
  below `/api/v1`; see [the payment & settlement core guide](docs/architecture/PHASE_5_PAYMENT_SETTLEMENT_CORE.md).
- Phase 6 operator compliance (admission, evidence, aircraft authorization,
  eligibility) is exposed below `/api/v1` and gates offers and booking
  confirmation; see [the operator compliance guide](docs/architecture/PHASE_6_OPERATOR_COMPLIANCE_MARKETPLACE_ADMISSION.md).
- Phase 7 operator financial onboarding (connected account, onboarding link,
  synchronize, financial eligibility) and the verified Stripe webhook endpoint are
  exposed below `/api/v1`; PSP-backed payments (Stripe test mode) require financial
  onboarding. See [the production payments & financial onboarding guide](docs/architecture/PHASE_7_PRODUCTION_PAYMENTS_OPERATOR_FINANCIAL_ONBOARDING.md).
- Phase 8 identity & access (registration, verification, login/logout, sessions,
  password reset, organizations, memberships, invitations, admin) is exposed below
  `/api/v1`; every non-public route is authenticated and authorized. See
  [the identity, access & organizations guide](docs/architecture/PHASE_8_IDENTITY_ACCESS_ORGANIZATIONS.md).

## Documentation

- [Product vision](docs/product/SKY_BRIDGE_JET_V1_PRODUCT_VISION.md)
- [Architecture and implementation plan](docs/architecture/SKY_BRIDGE_JET_V1_IMPLEMENTATION_PLAN.md)
- [Phase 2 core domain](docs/architecture/PHASE_2_CORE_DOMAIN.md)
- [Phase 3 quotes and operator offers](docs/architecture/PHASE_3_QUOTES_OPERATOR_OFFERS.md)
- [Phase 4 booking & reservation orchestration](docs/architecture/PHASE_4_BOOKING_RESERVATION_ORCHESTRATION.md)
- [Phase 5 payment & settlement core](docs/architecture/PHASE_5_PAYMENT_SETTLEMENT_CORE.md)
- [Phase 6 operator compliance & marketplace admission](docs/architecture/PHASE_6_OPERATOR_COMPLIANCE_MARKETPLACE_ADMISSION.md)
- [Phase 7 production payments & operator financial onboarding](docs/architecture/PHASE_7_PRODUCTION_PAYMENTS_OPERATOR_FINANCIAL_ONBOARDING.md)
- [Phase 8 identity, access & organizations](docs/architecture/PHASE_8_IDENTITY_ACCESS_ORGANIZATIONS.md)
- [Architecture decisions](docs/decisions/)
