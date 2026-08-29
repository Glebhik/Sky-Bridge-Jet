"""Pure-unit tests for password/token security and the authorization policy.

No database or HTTP is required — these pin the crypto boundary and the central
allow/deny decision.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from sky_bridge_jet.core.config import Settings
from sky_bridge_jet.modules.iam.authz import (
    MembershipContext,
    Principal,
    ResourceScope,
    authorize,
    is_authorized,
)
from sky_bridge_jet.modules.iam.domain import (
    AuthenticationError,
    AuthorizationError,
    IamError,
    OrganizationRole,
    OrganizationType,
    Permission,
    UserStatus,
    normalize_email,
    validate_password,
)
from sky_bridge_jet.modules.iam.security import (
    generate_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    tokens_equal,
    verify_password,
)


# -- Security primitives -----------------------------------------------------
def test_password_hash_is_argon2id_and_verifies() -> None:
    hashed = hash_password("CorrectHorse12")
    assert hashed.startswith("$argon2id$")
    assert "CorrectHorse12" not in hashed
    assert verify_password(hashed, "CorrectHorse12") is True
    assert verify_password(hashed, "WrongPassword99") is False


def test_password_hash_is_salted_unique() -> None:
    assert hash_password("CorrectHorse12") != hash_password("CorrectHorse12")


def test_verify_rejects_garbage_hash_without_raising() -> None:
    assert verify_password("not-a-hash", "whatever") is False
    assert password_needs_rehash("not-a-hash") is True


def test_token_hash_is_deterministic_and_hides_secret() -> None:
    token = generate_token()
    digest = hash_token(token)
    assert token not in digest
    assert len(digest) == 64
    assert hash_token(token) == digest
    assert tokens_equal(hash_token(token), digest) is True
    assert tokens_equal(hash_token(generate_token()), digest) is False


def test_password_policy() -> None:
    with pytest.raises(IamError):
        validate_password("short1A")
    with pytest.raises(IamError):
        validate_password("alllowercase12")  # no upper case
    assert validate_password("CorrectHorse12") == "CorrectHorse12"


def test_normalize_email() -> None:
    assert normalize_email("  Owner@Example.COM ") == "owner@example.com"
    with pytest.raises(IamError):
        normalize_email("not-an-email")


# -- Cookie security ---------------------------------------------------------
def test_cookie_secure_only_in_production() -> None:
    assert Settings(app_environment="development").cookie_secure_effective is False
    assert Settings(app_environment="test").cookie_secure_effective is False
    assert (
        Settings(
            app_environment="production",
            database_url="postgresql+psycopg://u:p@db/x",
            privileged_identity_provider="auth0",
            auth0_issuer="https://example.eu.auth0.com",
            auth0_client_id="production-client",
            auth0_callback_url="https://app.example/auth/callback",
            auth0_environment_id="production",
        ).cookie_secure_effective
        is True
    )


def test_production_forbids_disabling_secure_cookie() -> None:
    with pytest.raises(ValueError, match="SESSION_COOKIE_SECURE"):
        Settings(
            app_environment="production",
            database_url="postgresql+psycopg://u:p@db/x",
            session_cookie_secure=False,
        )


# -- Authorization policy ----------------------------------------------------
def _principal(
    *memberships: MembershipContext, status: UserStatus = UserStatus.ACTIVE
) -> Principal:
    return Principal(
        user_id=uuid4(), session_id=uuid4(), status=status, memberships=tuple(memberships)
    )


def _customer_member(customer_id) -> MembershipContext:
    return MembershipContext(
        organization_id=uuid4(),
        organization_type=OrganizationType.CUSTOMER,
        role=OrganizationRole.CUSTOMER_OWNER,
        customer_id=customer_id,
    )


def test_customer_owner_can_access_own_but_not_other_customer() -> None:
    a, b = uuid4(), uuid4()
    principal = _principal(_customer_member(a))
    assert is_authorized(principal, Permission.TRIP_READ, ResourceScope.customer(a)) is True
    assert is_authorized(principal, Permission.TRIP_READ, ResourceScope.customer(b)) is False


def test_operator_scope_isolation() -> None:
    op_a, op_b = uuid4(), uuid4()
    principal = _principal(
        MembershipContext(
            organization_id=uuid4(),
            organization_type=OrganizationType.OPERATOR,
            role=OrganizationRole.OPERATOR_SALES,
            operator_id=op_a,
        )
    )
    assert is_authorized(principal, Permission.OFFER_MANAGE, ResourceScope.operator(op_a)) is True
    assert is_authorized(principal, Permission.OFFER_MANAGE, ResourceScope.operator(op_b)) is False
    # Operator sales cannot review compliance at all.
    assert is_authorized(principal, Permission.COMPLIANCE_REVIEW, ResourceScope.global_()) is False


def test_platform_role_is_cross_tenant_for_its_permissions_only() -> None:
    reviewer = _principal(
        MembershipContext(
            organization_id=uuid4(),
            organization_type=OrganizationType.PLATFORM,
            role=OrganizationRole.PLATFORM_COMPLIANCE_REVIEWER,
        )
    )
    # Cross-tenant compliance review is allowed.
    assert is_authorized(reviewer, Permission.COMPLIANCE_REVIEW, ResourceScope.global_()) is True
    assert (
        is_authorized(reviewer, Permission.OPERATOR_READ, ResourceScope.operator(uuid4())) is True
    )
    # But the reviewer holds no admin or refund capability.
    assert is_authorized(reviewer, Permission.PAYMENT_REFUND, ResourceScope.global_()) is False
    assert is_authorized(reviewer, Permission.ADMIN_USERS_MANAGE, ResourceScope.global_()) is False


def test_suspended_principal_is_never_authorized() -> None:
    principal = _principal(_customer_member(uuid4()), status=UserStatus.SUSPENDED)
    scope = ResourceScope.customer(principal.memberships[0].customer_id)  # type: ignore[arg-type]
    assert is_authorized(principal, Permission.TRIP_READ, scope) is False
    with pytest.raises(AuthenticationError):
        authorize(principal, Permission.TRIP_READ, scope)


def test_authorize_raises_authorization_error_when_denied() -> None:
    principal = _principal(_customer_member(uuid4()))
    with pytest.raises(AuthorizationError):
        authorize(principal, Permission.COMPLIANCE_REVIEW, ResourceScope.global_())


def test_product_owner_has_every_permission() -> None:
    owner = _principal(
        MembershipContext(
            organization_id=uuid4(),
            organization_type=OrganizationType.PLATFORM,
            role=OrganizationRole.PRODUCT_OWNER,
        )
    )
    for permission in Permission:
        assert is_authorized(owner, permission, ResourceScope.global_()) is True
