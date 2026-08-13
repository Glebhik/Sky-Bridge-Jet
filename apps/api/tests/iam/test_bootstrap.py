"""First-product-owner bootstrap (DB-backed): auditable, and disabled afterward."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.iam.domain import (
    LastAdminError,
    MembershipStatus,
    OrganizationRole,
    UserStatus,
)
from sky_bridge_jet.modules.iam.models import AuthAuditLog, OrganizationMembership
from sky_bridge_jet.modules.iam.services import bootstrap_product_owner

requires_db = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)


def _product_owner_exists() -> bool:
    with SessionLocal() as session:
        return (
            session.query(OrganizationMembership)
            .filter(
                OrganizationMembership.role == OrganizationRole.PRODUCT_OWNER,
                OrganizationMembership.status == MembershipStatus.ACTIVE,
            )
            .first()
            is not None
        )


@requires_db
def test_bootstrap_creates_owner_then_refuses_second() -> None:
    email = f"owner+{uuid4().hex[:8]}@example.com"
    if not _product_owner_exists():
        with SessionLocal() as session:
            user, org = bootstrap_product_owner(
                session, email=email, password="CorrectHorse12", display_name="Owner"
            )
        assert user.status is UserStatus.ACTIVE
        assert user.email_verified_at is not None
        with SessionLocal() as session:
            audit = (
                session.query(AuthAuditLog)
                .filter(AuthAuditLog.event == "product_owner_bootstrapped")
                .first()
            )
            assert audit is not None

    # Regardless of prior state, a product owner now exists and bootstrap is disabled.
    with SessionLocal() as session, pytest.raises(LastAdminError):
        bootstrap_product_owner(
            session, email=f"second+{uuid4().hex[:8]}@example.com", password="CorrectHorse12"
        )


@requires_db
def test_bootstrap_rejects_weak_password() -> None:
    from sky_bridge_jet.modules.iam.domain import IamError

    with SessionLocal() as session, pytest.raises(IamError):
        bootstrap_product_owner(
            session, email=f"weak+{uuid4().hex[:8]}@example.com", password="short"
        )
