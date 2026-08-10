"""Initialize the migration history.

Revision ID: 20260810_0001
Revises:
Create Date: 2026-08-10 00:00:00
"""

from collections.abc import Sequence

revision: str = "20260810_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the Alembic version marker before domain tables exist."""


def downgrade() -> None:
    """Remove no schema objects; this baseline has no domain tables."""
