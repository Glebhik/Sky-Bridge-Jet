"""Phase 9.1.A — authenticated customer-account recovery (ADR-047), DB-backed.

Covers the full Section-10 matrix: invitation precedence at verification time and at
recovery; account-state eligibility; idempotency and real-PostgreSQL concurrency
(recovery×recovery and acceptance×recovery); atomic rollback of a provisioning or audit
failure at both verification time and recovery; and the safe audit event. A "stranded"
user is an ACTIVE, verified user with no membership — reproduced exactly as it arises in
production: a *valid* pending invitation existed at verification (so self-provisioning was
skipped) and later lapsed.
"""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import iam_support
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from sky_bridge_jet.core.config import get_settings
from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.iam import provisioning as provisioning_module
from sky_bridge_jet.modules.iam import repositories as repositories_module
from sky_bridge_jet.modules.iam.domain import (
    AccountRecoveryIneligibleError,
    InvitationStatus,
    MembershipStatus,
    OrganizationRole,
    OrganizationType,
    UserStatus,
)
from sky_bridge_jet.modules.iam.models import (
    AuthAuditLog,
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
    User,
)
from sky_bridge_jet.modules.iam.provisioning import (
    CUSTOMER_ACCOUNT_RECOVERED_EVENT,
    CUSTOMER_SELF_PROVISIONED_EVENT,
    recover_personal_customer,
)
from sky_bridge_jet.modules.iam.security import generate_token, hash_token
from sky_bridge_jet.modules.iam.services import AuthService

requires_db = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)

RECOVER_URL = "/api/v1/auth/customer-account/recover"
_SESSION_COOKIE = get_settings().session_cookie_name
_PASSWORD = "CorrectHorse12"


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
def _insert_invitation(
    email: str,
    *,
    status: InvitationStatus = InvitationStatus.PENDING,
    expires_delta: timedelta = timedelta(days=7),
    raw_token: str | None = None,
) -> tuple[UUID, UUID]:
    """Insert an invitation on a PLATFORM org (no FK on customer/operator). Returns
    (invitation_id, organization_id). ``raw_token`` lets a test accept it via the API."""
    with SessionLocal() as session, session.begin():
        org = Organization(organization_type=OrganizationType.PLATFORM, display_name="Inviting Org")
        session.add(org)
        session.flush()
        invitation = OrganizationInvitation(
            organization_id=org.id,
            invited_email_normalized=email.strip().lower(),
            role=OrganizationRole.PLATFORM_ADMIN,
            token_hash=hash_token(raw_token) if raw_token else uuid4().hex,
            status=status,
            expires_at=datetime.now(UTC) + expires_delta,
        )
        session.add(invitation)
        session.flush()
        return invitation.id, org.id


def _lapse_invitation(invitation_id: UUID, *, expire: bool = False, revoke: bool = False) -> None:
    with SessionLocal() as session, session.begin():
        invitation = session.get(OrganizationInvitation, invitation_id)
        assert invitation is not None
        if expire:
            invitation.expires_at = datetime.now(UTC) - timedelta(days=1)
        if revoke:
            invitation.status = InvitationStatus.REVOKED


def _stranded_user(email: str | None = None, *, lapse: str = "expire") -> tuple[TestClient, UUID]:
    """An ACTIVE, verified, membership-less user with a logged-in client.

    A valid pending invitation exists at verification (self-provisioning is skipped),
    then it is lapsed per ``lapse`` (``"expire"``/``"revoke"``/``"keep"``).
    """
    email = email or f"strand+{uuid4().hex[:10]}@example.com"
    holder: dict[str, UUID] = {}

    def _before_verify(_user_id: UUID) -> None:
        holder["inv"], _ = _insert_invitation(email)

    client = iam_support.new_client()
    user_id = iam_support.register_verify_login(client, email=email, before_verify=_before_verify)
    if lapse == "expire":
        _lapse_invitation(holder["inv"], expire=True)
    elif lapse == "revoke":
        _lapse_invitation(holder["inv"], revoke=True)
    return client, user_id


def _register_only(email: str) -> str:
    """Register without verifying; return the raw verification token."""
    client = iam_support.new_client()
    resp = client.post("/api/v1/auth/register", json={"email": email, "password": _PASSWORD})
    assert resp.status_code == 201, resp.text
    return str(resp.json()["verification_token"])


def _personal_customer_orgs(user_id: UUID) -> int:
    """Count the user's active CUSTOMER_OWNER memberships in CUSTOMER organizations."""
    with SessionLocal() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(OrganizationMembership)
                .join(Organization, Organization.id == OrganizationMembership.organization_id)
                .where(
                    OrganizationMembership.user_id == user_id,
                    OrganizationMembership.status == MembershipStatus.ACTIVE,
                    OrganizationMembership.role == OrganizationRole.CUSTOMER_OWNER,
                    Organization.organization_type == OrganizationType.CUSTOMER,
                )
            )
            or 0
        )


def _membership_count(user_id: UUID) -> int:
    with SessionLocal() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(OrganizationMembership)
                .where(
                    OrganizationMembership.user_id == user_id,
                    OrganizationMembership.status == MembershipStatus.ACTIVE,
                )
            )
            or 0
        )


def _set_status(user_id: UUID, status: UserStatus) -> None:
    with SessionLocal() as session, session.begin():
        user = session.get(User, user_id)
        assert user is not None
        user.status = status


def _clone_authenticated(client: TestClient) -> TestClient:
    """A second client sharing the same session cookie + CSRF header (same principal)."""
    twin = iam_support.new_client()
    for name, value in client.cookies.items():
        twin.cookies.set(name, value)
    csrf = client.headers.get("X-CSRF-Token")
    if csrf:
        twin.headers["X-CSRF-Token"] = csrf
    return twin


def _recovered_events(user_id: UUID) -> int:
    with SessionLocal() as session:
        return len(
            list(
                session.scalars(
                    select(AuthAuditLog).where(
                        AuthAuditLog.user_id == user_id,
                        AuthAuditLog.event == CUSTOMER_ACCOUNT_RECOVERED_EVENT,
                    )
                ).all()
            )
        )


# --------------------------------------------------------------------------- #
# Invitation precedence at verification time (items 1, 3, 4)
# --------------------------------------------------------------------------- #
@requires_db
def test_valid_pending_invitation_suppresses_verification_provisioning() -> None:
    email = f"inv-valid+{uuid4().hex[:8]}@example.com"
    client, user_id = _stranded_user(email, lapse="keep")  # invitation stays valid
    assert _personal_customer_orgs(user_id) == 0  # provisioning skipped at verify


@requires_db
def test_expired_invitation_does_not_suppress_verification_provisioning() -> None:
    # An already-expired invitation present at verification does not block provisioning.
    email = f"inv-exp+{uuid4().hex[:8]}@example.com"
    inv_holder: dict[str, UUID] = {}

    def _before(_uid: UUID) -> None:
        inv_holder["inv"], _ = _insert_invitation(email, expires_delta=timedelta(days=-1))

    client = iam_support.new_client()
    user_id = iam_support.register_verify_login(client, email=email, before_verify=_before)
    assert _personal_customer_orgs(user_id) == 1  # a personal tenant was provisioned


@requires_db
def test_revoked_invitation_does_not_suppress_verification_provisioning() -> None:
    email = f"inv-rev+{uuid4().hex[:8]}@example.com"
    inv_holder: dict[str, UUID] = {}

    def _before(_uid: UUID) -> None:
        inv_holder["inv"], _ = _insert_invitation(email, status=InvitationStatus.REVOKED)

    client = iam_support.new_client()
    user_id = iam_support.register_verify_login(client, email=email, before_verify=_before)
    assert _personal_customer_orgs(user_id) == 1


# --------------------------------------------------------------------------- #
# Recovery eligibility & denial (items 2, 5, 6, 7, 8, 9, 10, 11, 16)
# --------------------------------------------------------------------------- #
@requires_db
def test_stranded_user_recovers_exactly_one_personal_tenant() -> None:
    client, user_id = _stranded_user(lapse="expire")
    assert _personal_customer_orgs(user_id) == 0
    resp = client.post(RECOVER_URL)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["role"] == "CUSTOMER_OWNER"
    assert body["organization_type"] == "CUSTOMER"
    assert UUID(body["organization_id"]) and UUID(body["customer_id"])
    assert _personal_customer_orgs(user_id) == 1
    # The recovered account now has a working customer context.
    assert client.get("/api/v1/me/bookings").status_code == 200


@requires_db
def test_expired_invitation_does_not_block_recovery() -> None:
    client, user_id = _stranded_user(lapse="expire")
    assert client.post(RECOVER_URL).status_code == 201
    assert _personal_customer_orgs(user_id) == 1


@requires_db
def test_revoked_invitation_does_not_block_recovery() -> None:
    client, user_id = _stranded_user(lapse="revoke")
    assert client.post(RECOVER_URL).status_code == 201
    assert _personal_customer_orgs(user_id) == 1


@requires_db
def test_valid_pending_invitation_blocks_recovery() -> None:
    client, user_id = _stranded_user(lapse="keep")
    resp = client.post(RECOVER_URL)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "pending_invitation_exists"
    assert _personal_customer_orgs(user_id) == 0
    # The safe error discloses no inviting organization / issuer / role.
    body = resp.text.lower()
    assert "organization_id" not in body and "role=" not in body


@requires_db
def test_existing_membership_blocks_recovery() -> None:
    # A normally self-provisioned user already has a personal tenant → 409, no duplicate.
    client = iam_support.new_client()
    user_id = iam_support.register_verify_login(client)
    resp = client.post(RECOVER_URL)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "account_already_provisioned"
    assert _personal_customer_orgs(user_id) == 1


@requires_db
def test_repeated_recovery_creates_no_duplicate_tenant() -> None:
    client, user_id = _stranded_user(lapse="expire")
    assert client.post(RECOVER_URL).status_code == 201
    second = client.post(RECOVER_URL)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "account_already_provisioned"
    assert _personal_customer_orgs(user_id) == 1


@requires_db
def test_suspended_user_cannot_recover() -> None:
    client, user_id = _stranded_user(lapse="expire")
    _set_status(user_id, UserStatus.SUSPENDED)  # non-ACTIVE sessions stop resolving
    resp = client.post(RECOVER_URL)
    assert resp.status_code == 401  # denied at the authentication gate
    assert _personal_customer_orgs(user_id) == 0


@requires_db
def test_disabled_user_cannot_recover() -> None:
    client, user_id = _stranded_user(lapse="expire")
    _set_status(user_id, UserStatus.DISABLED)
    resp = client.post(RECOVER_URL)
    assert resp.status_code == 401
    assert _personal_customer_orgs(user_id) == 0


@requires_db
def test_recovery_service_denies_non_active_locked_user() -> None:
    # Defense in depth: if the locked row is not ACTIVE, the service raises 403 even
    # though the gate normally preempts this with a 401.
    _client, user_id = _stranded_user(lapse="expire")
    _set_status(user_id, UserStatus.SUSPENDED)
    with SessionLocal() as session, pytest.raises(AccountRecoveryIneligibleError):
        recover_personal_customer(session, user_id)
    assert _personal_customer_orgs(user_id) == 0


@requires_db
def test_unverified_user_cannot_recover() -> None:
    # A never-verified user holds no session → the gate rejects the request (401).
    email = f"unverified+{uuid4().hex[:8]}@example.com"
    _register_only(email)
    anon = iam_support.new_client()
    assert anon.post(RECOVER_URL).status_code == 401


@requires_db
def test_anonymous_recovery_is_rejected() -> None:
    assert iam_support.new_client().post(RECOVER_URL).status_code == 401


@requires_db
def test_missing_csrf_is_rejected() -> None:
    client, _user_id = _stranded_user(lapse="expire")
    client.headers.pop("X-CSRF-Token", None)
    assert client.post(RECOVER_URL).status_code == 403


@requires_db
def test_operator_membership_cannot_become_customer_ownership() -> None:
    admin = iam_support.product_owner_client()
    operator_id = iam_support.create_operator(admin)
    operator_client, org_id = iam_support.operator_role_client(
        operator_id, OrganizationRole.OPERATOR_ADMIN
    )
    with SessionLocal() as session:
        user_id = (
            session.scalars(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == org_id
                )
            )
            .one()
            .user_id
        )
    resp = operator_client.post(RECOVER_URL)
    assert resp.status_code == 409  # existing operator membership blocks recovery
    assert _personal_customer_orgs(user_id) == 0  # no CUSTOMER ownership was minted
    assert _membership_count(user_id) == 1  # the operator membership is untouched


@requires_db
def test_platform_membership_cannot_become_customer_ownership() -> None:
    client = iam_support.platform_role_client(OrganizationRole.PLATFORM_ADMIN)
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    user_id = UUID(me.json()["user"]["id"])
    resp = client.post(RECOVER_URL)
    assert resp.status_code == 409  # existing platform membership blocks recovery
    assert _personal_customer_orgs(user_id) == 0  # no CUSTOMER ownership was minted
    assert _membership_count(user_id) == 1  # the platform membership is untouched


# --------------------------------------------------------------------------- #
# Safe audit (item overlaps 9/16) and response shape
# --------------------------------------------------------------------------- #
@requires_db
def test_recovery_writes_one_safe_audit_and_no_self_provisioned_event() -> None:
    client, user_id = _stranded_user(lapse="expire")
    assert client.post(RECOVER_URL).status_code == 201
    with SessionLocal() as session:
        recovered = list(
            session.scalars(
                select(AuthAuditLog).where(
                    AuthAuditLog.user_id == user_id,
                    AuthAuditLog.event == CUSTOMER_ACCOUNT_RECOVERED_EVENT,
                )
            ).all()
        )
        self_prov = list(
            session.scalars(
                select(AuthAuditLog).where(
                    AuthAuditLog.user_id == user_id,
                    AuthAuditLog.event == CUSTOMER_SELF_PROVISIONED_EVENT,
                )
            ).all()
        )
    assert len(recovered) == 1 and len(self_prov) == 0  # the stranded user never self-provisioned
    record = recovered[0]
    assert record.organization_id is not None
    detail = (record.detail or "").lower()
    for forbidden in ("token", "password", "secret", "@", "csrf", "session"):
        assert forbidden not in detail


@requires_db
def test_denied_recovery_writes_no_success_event() -> None:
    client, user_id = _stranded_user(lapse="keep")  # blocked by pending invitation
    assert client.post(RECOVER_URL).status_code == 409
    assert _recovered_events(user_id) == 0


# --------------------------------------------------------------------------- #
# Atomic rollback — verification time (items 12, 13) and recovery (items 14, 15)
# --------------------------------------------------------------------------- #
class _Boom:
    """A drop-in for OrganizationMembership that fails on construction."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("injected provisioning failure")


def _assert_no_trace(email: str, user_id: UUID) -> None:
    with SessionLocal() as session:
        user = session.get(User, user_id)
        assert user is not None
        assert user.status is UserStatus.PENDING_VERIFICATION  # activation rolled back
        assert user.email_verified_at is None
        token = session.scalars(
            select(OrganizationInvitation).where(
                OrganizationInvitation.invited_email_normalized == email
            )
        ).first()
        # No customer/org/membership/audit was persisted for this user.
        assert _personal_customer_orgs(user_id) == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuthAuditLog)
                .where(
                    AuthAuditLog.user_id == user_id,
                    AuthAuditLog.event == CUSTOMER_SELF_PROVISIONED_EVENT,
                )
            )
            == 0
        )
        _ = token  # invitation state is irrelevant here


@requires_db
def test_provisioning_failure_during_verification_rolls_back_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"vfail+{uuid4().hex[:8]}@example.com"
    raw_token = _register_only(email)
    with SessionLocal() as session:
        user_id = session.scalars(select(User).where(User.normalized_email == email)).one().id
    monkeypatch.setattr(provisioning_module, "OrganizationMembership", _Boom)
    with SessionLocal() as session, pytest.raises(RuntimeError):
        AuthService(session).verify_email(raw_token)
    _assert_no_trace(email, user_id)
    # The single-use token was not consumed — verification can still be retried later.
    monkeypatch.undo()
    with SessionLocal() as session:
        AuthService(session).verify_email(raw_token)
    assert _personal_customer_orgs(user_id) == 1


@requires_db
def test_audit_failure_during_verification_rolls_back_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"afail+{uuid4().hex[:8]}@example.com"
    raw_token = _register_only(email)
    with SessionLocal() as session:
        user_id = session.scalars(select(User).where(User.normalized_email == email)).one().id

    original = repositories_module.AuditRepository.record

    def _boom(self: object, event: str, **kwargs: object) -> object:
        if event == CUSTOMER_SELF_PROVISIONED_EVENT:
            raise RuntimeError("injected audit failure")
        return original(self, event, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(repositories_module.AuditRepository, "record", _boom)
    with SessionLocal() as session, pytest.raises(RuntimeError):
        AuthService(session).verify_email(raw_token)
    _assert_no_trace(email, user_id)


@requires_db
def test_provisioning_failure_during_recovery_leaves_no_partial_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _client, user_id = _stranded_user(lapse="expire")
    monkeypatch.setattr(provisioning_module, "OrganizationMembership", _Boom)
    with SessionLocal() as session, pytest.raises(RuntimeError):
        recover_personal_customer(session, user_id)
    assert _personal_customer_orgs(user_id) == 0
    assert _recovered_events(user_id) == 0
    # A subsequent clean recovery still works (state is consistent, no partial rows).
    monkeypatch.undo()
    with SessionLocal() as session:
        recover_personal_customer(session, user_id)
    assert _personal_customer_orgs(user_id) == 1


@requires_db
def test_audit_failure_during_recovery_leaves_no_partial_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _client, user_id = _stranded_user(lapse="expire")
    original = repositories_module.AuditRepository.record

    def _boom(self: object, event: str, **kwargs: object) -> object:
        if event == CUSTOMER_ACCOUNT_RECOVERED_EVENT:
            raise RuntimeError("injected audit failure")
        return original(self, event, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(repositories_module.AuditRepository, "record", _boom)
    with SessionLocal() as session, pytest.raises(RuntimeError):
        recover_personal_customer(session, user_id)
    assert _personal_customer_orgs(user_id) == 0
    assert _recovered_events(user_id) == 0


# --------------------------------------------------------------------------- #
# Concurrency — real PostgreSQL (items 17, 18)
# --------------------------------------------------------------------------- #
@requires_db
def test_concurrent_recovery_creates_at_most_one_tenant() -> None:
    client, user_id = _stranded_user(lapse="expire")
    twins = [_clone_authenticated(client), _clone_authenticated(client)]
    barrier = threading.Barrier(len(twins))
    statuses: list[int] = []
    lock = threading.Lock()

    def _recover(twin: TestClient) -> None:
        barrier.wait()
        code = twin.post(RECOVER_URL).status_code
        with lock:
            statuses.append(code)

    threads = [threading.Thread(target=_recover, args=(twin,)) for twin in twins]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert statuses.count(201) == 1  # exactly one winner
    assert statuses.count(409) == 1  # the other gets the safe conflict
    assert _personal_customer_orgs(user_id) == 1  # never a duplicate tenant
    assert _recovered_events(user_id) == 1  # exactly one success audit


@requires_db
def test_concurrent_invitation_acceptance_and_recovery_is_consistent() -> None:
    # A stranded user holds a *valid* pending invitation with a known raw token. One
    # thread accepts it; the other attempts recovery. Whatever the interleaving, the
    # user ends with exactly the invited membership and no personal customer tenant.
    email = f"race+{uuid4().hex[:8]}@example.com"
    raw_token = generate_token()
    holder: dict[str, UUID] = {}

    def _before(_uid: UUID) -> None:
        holder["inv"], holder["org"] = _insert_invitation(email, raw_token=raw_token)

    client = iam_support.new_client()
    user_id = iam_support.register_verify_login(client, email=email, before_verify=_before)
    assert _membership_count(user_id) == 0  # stranded: invitation suppressed provisioning

    accept_client = _clone_authenticated(client)
    recover_client = _clone_authenticated(client)
    barrier = threading.Barrier(2)
    results: dict[str, int] = {}
    lock = threading.Lock()

    def _accept() -> None:
        barrier.wait()
        code = accept_client.post(
            "/api/v1/auth/invitations/accept", json={"token": raw_token}
        ).status_code
        with lock:
            results["accept"] = code

    def _recover() -> None:
        barrier.wait()
        code = recover_client.post(RECOVER_URL).status_code
        with lock:
            results["recover"] = code

    threads = [threading.Thread(target=_accept), threading.Thread(target=_recover)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results["accept"] == 200  # the invitation acceptance succeeds
    assert results["recover"] == 409  # recovery is blocked (pending invite or existing membership)
    assert _personal_customer_orgs(user_id) == 0  # no personal customer tenant was created
    assert _membership_count(user_id) == 1  # exactly the invited membership, no partial state
