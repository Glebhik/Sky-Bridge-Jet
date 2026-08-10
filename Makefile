.DEFAULT_GOAL := help

.PHONY: help setup setup-e2e dev dev-api dev-web test test-api test-api-integration test-web test-e2e lint lint-api lint-web format format-api format-web format-write build migrate migrate-compose docker-config

help:
	@printf "Targets: setup setup-e2e dev dev-api dev-web test test-api test-api-integration test-web test-e2e lint format format-write build migrate migrate-compose docker-config\n"

setup:
	corepack enable
	pnpm install --frozen-lockfile
	cd apps/api && uv sync --locked
	$(MAKE) setup-e2e

setup-e2e:
	pnpm setup:e2e

dev:
	docker compose up --build

dev-api:
	cd apps/api && uv run uvicorn sky_bridge_jet.main:app --reload

dev-web:
	pnpm --dir apps/web dev

test: test-api test-web

test-api:
	cd apps/api && uv run pytest

test-api-integration:
	cd apps/api && RUN_DATABASE_INTEGRATION=1 uv run pytest

test-web:
	pnpm --dir apps/web test

test-e2e:
	pnpm test:e2e

lint: lint-api lint-web

lint-api:
	cd apps/api && uv run ruff check .
	cd apps/api && uv run mypy src

lint-web:
	pnpm --dir apps/web lint
	pnpm --dir apps/web typecheck

format: format-api format-web

format-api:
	cd apps/api && uv run ruff format --check .

format-web:
	pnpm --dir apps/web format

format-write:
	cd apps/api && uv run ruff format .
	pnpm --dir apps/web format:write

build:
	pnpm --dir apps/web build

migrate:
	cd apps/api && uv run alembic upgrade head

migrate-compose:
	docker compose exec api /app/.venv/bin/alembic upgrade head

docker-config:
	docker compose config
