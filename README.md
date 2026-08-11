# Sky Bridge Jet

Sky Bridge Jet is a premium private aviation marketplace and charter intermediary.
It is a managed marketplace: licensed operators remain responsible for flight
operation and execution.

## Phase 5 status

This repository contains the Phase 1 engineering foundation, the Phase 2 core
private-aviation backend domain, the Phase 3 quotes and operator offers domain,
the Phase 4 booking and reservation orchestration domain, and the Phase 5
payment and settlement core. It provides a modular-monolith API shell, a
responsive Next.js shell, local PostgreSQL, migrations, test harnesses, and
pull-request CI. Phase 2 adds the core aviation domain. Phase 3 adds OperatorOffer
(operators offer, customer selects). Phase 4 adds Booking (operator confirms or
rejects). Phase 5 adds Payment: a provider-neutral financial state machine around
a booking — authorization, capture (after operator confirmation), void, refund,
operator/platform allocation, and settlement eligibility — using a deterministic
fake provider. **No real money moves.**

Phase 5 deliberately does **not** implement live Stripe/Adyen or any real PSP,
real money movement, wallets or custody, operator payouts, a tax/VAT engine,
invoices, credit notes, an accounting ledger, chargebacks, KYC/KYB, AML,
cancellation-fee calculation, real provider integrations, Empty Legs,
identity/auth workflows, portals, notifications, dispatch, crew, flight
operations, FX, or AI. Legal, PSD2/payments, tax, and aviation classifications
are documented as specialist-review gates, not solved in software.

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
<http://localhost:8000>. `NEXT_PUBLIC_API_BASE_URL` configures the browser-safe
API base URL; it defaults to `http://localhost:8000`.

Alternatively, run the dev-focused container stack with `make dev`. The Compose
API connects to the `db` service and the web service is available on port 3000.
After the stack is healthy, apply migrations inside the API image with
`make migrate-compose`, then load seed data with `make seed-airports-compose`.

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

## Documentation

- [Product vision](docs/product/SKY_BRIDGE_JET_V1_PRODUCT_VISION.md)
- [Architecture and implementation plan](docs/architecture/SKY_BRIDGE_JET_V1_IMPLEMENTATION_PLAN.md)
- [Phase 2 core domain](docs/architecture/PHASE_2_CORE_DOMAIN.md)
- [Phase 3 quotes and operator offers](docs/architecture/PHASE_3_QUOTES_OPERATOR_OFFERS.md)
- [Phase 4 booking & reservation orchestration](docs/architecture/PHASE_4_BOOKING_RESERVATION_ORCHESTRATION.md)
- [Phase 5 payment & settlement core](docs/architecture/PHASE_5_PAYMENT_SETTLEMENT_CORE.md)
- [Architecture decisions](docs/decisions/)
