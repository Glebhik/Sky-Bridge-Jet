"""Add Phase 8 identity, access & organizations.

Creates the human-identity and access-control schema: ``users`` (email unique by
case-normalized form, opaque PK), ``organizations`` (customer/operator/platform,
optionally linked one-to-one to the existing ``customers``/``operators`` aggregates
by reference — the aviation aggregates are not rewritten), ``organization_memberships``
(role per org, one ACTIVE per user+org via a partial unique index, history retained),
``user_sessions`` (only the token hash stored), the single-use hashed
``email_verification_tokens`` / ``password_reset_tokens`` / ``organization_invitations``,
and the append-only ``auth_audit_log``. Forward-only; existing data is untouched and
no user/organization is fabricated.

Revision ID: 20260813_0009
Revises: 20260811_0008
Create Date: 2026-08-13 00:09:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260813_0009"
down_revision: str | Sequence[str] | None = "20260811_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

user_status = postgresql.ENUM(
    "PENDING_VERIFICATION",
    "ACTIVE",
    "SUSPENDED",
    "DISABLED",
    name="user_status",
    create_type=False,
)
organization_type = postgresql.ENUM(
    "CUSTOMER", "OPERATOR", "PLATFORM", name="organization_type", create_type=False
)
membership_status = postgresql.ENUM(
    "ACTIVE", "REVOKED", name="membership_status", create_type=False
)
invitation_status = postgresql.ENUM(
    "PENDING", "ACCEPTED", "REVOKED", "EXPIRED", name="invitation_status", create_type=False
)
organization_role = postgresql.ENUM(
    "CUSTOMER_OWNER",
    "CUSTOMER_ASSISTANT",
    "OPERATOR_ADMIN",
    "OPERATOR_SALES",
    "OPERATOR_OPERATIONS",
    "OPERATOR_FINANCE",
    "OPERATOR_COMPLIANCE",
    "PLATFORM_ADMIN",
    "PLATFORM_COMPLIANCE_REVIEWER",
    "PLATFORM_FINANCE_REVIEWER",
    "PLATFORM_SUPPORT",
    "PRODUCT_OWNER",
    name="organization_role",
    create_type=False,
)


def upgrade() -> None:
    """Create identity/access enum types and tables."""
    from alembic import op

    bind = op.get_bind()
    user_status.create(bind, checkfirst=True)
    organization_type.create(bind, checkfirst=True)
    membership_status.create(bind, checkfirst=True)
    invitation_status.create(bind, checkfirst=True)
    organization_role.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("normalized_email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("password_hash", sa.String(length=512), nullable=True),
        sa.Column("status", user_status, nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_email", name="uq_users_normalized_email"),
    )

    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_type", organization_type, nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=True),
        sa.Column("operator_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["operator_id"], ["operators.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id", name="uq_organizations_customer"),
        sa.UniqueConstraint("operator_id", name="uq_organizations_operator"),
    )
    op.create_index("ix_organizations_type", "organizations", ["organization_type"], unique=False)

    op.create_table(
        "organization_memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("role", organization_role, nullable=False),
        sa.Column("status", membership_status, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memberships_organization_id", "organization_memberships", ["organization_id"]
    )
    op.create_index("ix_memberships_user_id", "organization_memberships", ["user_id"])
    # At most one ACTIVE membership per (user, organization); history is retained.
    op.create_index(
        "uq_active_membership_user_org",
        "organization_memberships",
        ["user_id", "organization_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_user_sessions_token_hash"),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])

    for table, index_prefix, extra in (
        ("email_verification_tokens", "email_verification", "uq_email_verification_token_hash"),
        ("password_reset_tokens", "password_reset", "uq_password_reset_token_hash"),
    ):
        op.create_table(
            table,
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash", name=extra),
        )
        op.create_index(f"ix_{index_prefix}_user_id", table, ["user_id"])

    op.create_table(
        "organization_invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("invited_email_normalized", sa.String(length=320), nullable=False),
        sa.Column("role", organization_role, nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("status", invitation_status, nullable=False),
        sa.Column("invited_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_org_invitation_token_hash"),
    )
    op.create_index(
        "ix_org_invitation_organization_id", "organization_invitations", ["organization_id"]
    )

    op.create_table(
        "auth_audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event", sa.String(length=80), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("detail", sa.String(length=300), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auth_audit_user_id", "auth_audit_log", ["user_id"])
    op.create_index("ix_auth_audit_event", "auth_audit_log", ["event"])


def downgrade() -> None:
    """Drop the identity/access schema and its enum types."""
    from alembic import op

    op.drop_table("auth_audit_log")
    op.drop_table("organization_invitations")
    op.drop_table("password_reset_tokens")
    op.drop_table("email_verification_tokens")
    op.drop_table("user_sessions")
    op.drop_table("organization_memberships")
    op.drop_table("organizations")
    op.drop_table("users")

    bind = op.get_bind()
    organization_role.drop(bind, checkfirst=True)
    invitation_status.drop(bind, checkfirst=True)
    membership_status.drop(bind, checkfirst=True)
    organization_type.drop(bind, checkfirst=True)
    user_status.drop(bind, checkfirst=True)
