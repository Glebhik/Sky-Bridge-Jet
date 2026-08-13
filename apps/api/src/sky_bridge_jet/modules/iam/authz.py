"""The single authorization policy layer.

Every authorization decision is ``authorize(principal, permission, scope)``:

    WHO (principal + status)
    + PERMISSION (from role→permission matrix)
    + RESOURCE SCOPE (global / customer / operator ownership)
    → ALLOW or raise.

RBAC alone is insufficient — two CUSTOMER_OWNERs both hold ``trip.read`` but must
not read each other's trips — so scope binds a permission to the tenant the
principal is actually a member of. Platform roles are cross-tenant only for the
permissions their role grants. String role checks never appear outside this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from sky_bridge_jet.modules.iam.domain import (
    AuthenticationError,
    AuthorizationError,
    OrganizationRole,
    OrganizationType,
    Permission,
    UserStatus,
    permissions_for_role,
)


@dataclass(frozen=True)
class MembershipContext:
    """One active membership resolved for a principal, with its tenant links."""

    organization_id: UUID
    organization_type: OrganizationType
    role: OrganizationRole
    customer_id: UUID | None = None
    operator_id: UUID | None = None

    @property
    def permissions(self) -> frozenset[Permission]:
        return permissions_for_role(self.role)


@dataclass(frozen=True)
class Principal:
    """The authenticated actor for one request. Built by the auth dependency."""

    user_id: UUID
    session_id: UUID
    status: UserStatus
    memberships: tuple[MembershipContext, ...] = field(default_factory=tuple)
    active_organization_id: UUID | None = None

    @property
    def is_active(self) -> bool:
        return self.status is UserStatus.ACTIVE

    def granting_memberships(self, permission: Permission) -> list[MembershipContext]:
        return [m for m in self.memberships if permission in m.permissions]

    def has_permission(self, permission: Permission) -> bool:
        return any(permission in m.permissions for m in self.memberships)

    def all_permissions(self) -> set[Permission]:
        perms: set[Permission] = set()
        for m in self.memberships:
            perms |= m.permissions
        return perms


class ScopeKind(StrEnum):
    GLOBAL = "GLOBAL"
    CUSTOMER = "CUSTOMER"
    OPERATOR = "OPERATOR"


@dataclass(frozen=True)
class ResourceScope:
    """The tenant a permission is being exercised against."""

    kind: ScopeKind
    customer_id: UUID | None = None
    operator_id: UUID | None = None

    @classmethod
    def global_(cls) -> ResourceScope:
        """Platform-level: no tenant ownership (e.g. admin.users.manage)."""
        return cls(kind=ScopeKind.GLOBAL)

    @classmethod
    def customer(cls, customer_id: UUID) -> ResourceScope:
        return cls(kind=ScopeKind.CUSTOMER, customer_id=customer_id)

    @classmethod
    def operator(cls, operator_id: UUID) -> ResourceScope:
        return cls(kind=ScopeKind.OPERATOR, operator_id=operator_id)


def is_authorized(principal: Principal, permission: Permission, scope: ResourceScope) -> bool:
    """Pure allow/deny decision. Central, deterministic, and unit-testable."""
    if not principal.is_active:
        return False
    granting = principal.granting_memberships(permission)
    if not granting:
        return False
    if scope.kind is ScopeKind.GLOBAL:
        return True
    for membership in granting:
        # A platform role that grants the permission is cross-tenant for it.
        if membership.organization_type is OrganizationType.PLATFORM:
            return True
        if (
            scope.kind is ScopeKind.CUSTOMER
            and membership.organization_type is OrganizationType.CUSTOMER
            and membership.customer_id is not None
            and membership.customer_id == scope.customer_id
        ):
            return True
        if (
            scope.kind is ScopeKind.OPERATOR
            and membership.organization_type is OrganizationType.OPERATOR
            and membership.operator_id is not None
            and membership.operator_id == scope.operator_id
        ):
            return True
    return False


def authorize(principal: Principal, permission: Permission, scope: ResourceScope) -> None:
    """Enforce a decision, raising a safe typed error on denial.

    A non-active principal raises :class:`AuthenticationError` (401); an active but
    unentitled principal raises :class:`AuthorizationError` (403). Callers decide
    404-vs-403 masking for enumeration-sensitive resources.
    """
    if not principal.is_active:
        raise AuthenticationError("Authentication is required")
    if not is_authorized(principal, permission, scope):
        raise AuthorizationError("You are not permitted to perform this action")
