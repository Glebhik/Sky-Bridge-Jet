"""Add privileged external identity links and MFA session assurance.

Revision ID: 20260831_0014
Revises: 20260830_0013
"""

from collections.abc import Sequence

import sqlalchemy as sa

revision: str = "20260831_0014"
down_revision: str | Sequence[str] | None = "20260830_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from alembic import op

    op.create_table(
        "external_identity_links",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("issuer", sa.String(512), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("issuer", "subject", name="uq_external_identity_issuer_subject"),
        sa.UniqueConstraint("provider", "user_id", name="uq_external_identity_provider_user"),
    )
    op.create_index("ix_external_identity_user_id", "external_identity_links", ["user_id"])
    op.create_table(
        "privileged_auth_transactions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("state_hash", sa.String(64), nullable=False),
        sa.Column("nonce", sa.String(128), nullable=False),
        sa.Column("pkce_verifier", sa.String(128), nullable=False),
        sa.Column("return_path", sa.String(255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("state_hash", name="uq_privileged_auth_transaction_state"),
    )
    op.create_index(
        "ix_privileged_auth_transaction_expires", "privileged_auth_transactions", ["expires_at"]
    )
    op.add_column("user_sessions", sa.Column("identity_provider", sa.String(32), nullable=True))
    op.add_column("user_sessions", sa.Column("external_identity_link_id", sa.Uuid(), nullable=True))
    op.add_column(
        "user_sessions", sa.Column("provider_auth_time", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "user_sessions", sa.Column("mfa_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "user_sessions",
        sa.Column("assurance_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "user_sessions", sa.Column("provider_session_reference", sa.String(255), nullable=True)
    )
    op.create_foreign_key(
        "fk_user_sessions_external_identity_link",
        "user_sessions",
        "external_identity_links",
        ["external_identity_link_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    from alembic import op

    op.drop_constraint(
        "fk_user_sessions_external_identity_link", "user_sessions", type_="foreignkey"
    )
    for column in (
        "provider_session_reference",
        "assurance_expires_at",
        "mfa_verified_at",
        "provider_auth_time",
        "external_identity_link_id",
        "identity_provider",
    ):
        op.drop_column("user_sessions", column)
    op.drop_table("privileged_auth_transactions")
    op.drop_table("external_identity_links")
