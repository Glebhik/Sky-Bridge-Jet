# ADR-008: Reproducible package management for Phase 1

## Status

Accepted

## Decision

Use pnpm 11.21.0 workspaces with the committed root `pnpm-lock.yaml` for web
dependencies. Use uv 0.12.3 with committed `apps/api/uv.lock` for Python
dependencies.

## Consequences

Install commands use `--frozen-lockfile` or `--locked` in CI and Docker builds.
This keeps Phase 1 dependency resolution reproducible without creating unused
shared packages.
