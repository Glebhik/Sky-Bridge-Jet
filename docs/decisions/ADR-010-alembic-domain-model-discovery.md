# ADR-010: Alembic domain-model discovery convention

## Status

Accepted

## Decision

Alembic imports every `models.py` beneath
`sky_bridge_jet.modules.<bounded_context>` before reading `Base.metadata`.

## Consequences

Future bounded contexts must place SQLAlchemy mappings in that convention. This
keeps autogeneration reliable without a manually maintained import list. Phase 1
contains no domain modules or models.
