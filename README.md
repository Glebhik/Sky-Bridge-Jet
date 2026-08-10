# Sky Bridge Jet

Sky Bridge Jet is a premium private aviation marketplace and charter intermediary.
It is a managed marketplace: licensed operators remain responsible for flight
operation and execution.

## Phase 1 status

This repository contains the Phase 1 engineering foundation only. It provides a
modular-monolith API shell, a responsive Next.js shell, local PostgreSQL,
migrations, test harnesses, and pull-request CI. It deliberately does **not**
implement customer, passenger, operator, aircraft, airport, trip request,
quote, pricing, booking, Empty Leg, payment, authentication, or portal
business workflows.

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

1. Copy the development examples: `cp .env.example .env`.
2. Install dependencies: `make setup`.
3. Start PostgreSQL: `docker compose up -d db`.
4. Apply migrations: `make migrate`.
5. Run the API: `make dev-api`.
6. Run the web shell in another terminal: `make dev-web`.

The web app runs at <http://localhost:3000>; the API runs at
<http://localhost:8000>. `NEXT_PUBLIC_API_BASE_URL` configures the browser-safe
API base URL; it defaults to `http://localhost:8000`.

Alternatively, run the dev-focused container stack with `make dev`. The Compose
API connects to the `db` service and the web service is available on port 3000.

The values in `.env.example` are development examples only. Do not commit a
real `.env` or any credentials.

## Database and migrations

`DATABASE_URL` may be supplied directly. Otherwise the API builds it from
`DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD`, `DATABASE_HOST`, and
`DATABASE_PORT`. Production configuration rejects the checked-in development
password and a localhost database host.

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

Alembic discovers models through `sky_bridge_jet.db.base.Base.metadata`. The
baseline migration intentionally contains no business schema.

## Quality commands

```sh
make test          # API pytest and web Vitest suites
make test-e2e      # Playwright browser smoke test
make lint          # Ruff, mypy, ESLint, TypeScript
make format        # Ruff and Prettier format checks
make format-write  # Apply Ruff and Prettier formatting
make build         # Next.js production build
make docker-config # Validate Docker Compose configuration
```

Platform endpoints:

- `GET /health` returns `{"status":"ok"}` without a database dependency.
- `GET /ready` checks PostgreSQL with `SELECT 1`; it returns HTTP 503 and a
  non-sensitive unavailable status when PostgreSQL cannot be reached.
- `GET /api/v1` establishes the versioned API namespace without business
  endpoints.

## Documentation

- [Product vision](docs/product/SKY_BRIDGE_JET_V1_PRODUCT_VISION.md)
- [Architecture and implementation plan](docs/architecture/SKY_BRIDGE_JET_V1_IMPLEMENTATION_PLAN.md)
- [Architecture decisions](docs/decisions/)
