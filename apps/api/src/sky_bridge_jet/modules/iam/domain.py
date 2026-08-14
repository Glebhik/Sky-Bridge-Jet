"""Phase 8 identity & access domain: users, organizations, roles, permissions.

This module is the single source of truth for *what a principal may do*. Roles map
to a fixed permission vocabulary; a centralized policy (see :mod:`authz`) combines
permission with organization/resource scope. String role checks are never scattered
across routers — callers ask for a :class:`Permission`, not a role name.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Final

from sky_bridge_jet.modules.core_aviation.domain import DomainError


# --------------------------------------------------------------------------- #
# Lifecycles
# --------------------------------------------------------------------------- #
class UserStatus(StrEnum):
    """A human account lifecycle. A non-ACTIVE user exercises no privilege."""

    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISABLED = "DISABLED"


class OrganizationType(StrEnum):
    """The kind of account context a human acts within.

    Distinct from the aviation/commercial ``Customer``/``Operator`` aggregates: an
    organization represents *human access* to those entities, linked by reference.
    """

    CUSTOMER = "CUSTOMER"
    OPERATOR = "OPERATOR"
    PLATFORM = "PLATFORM"


class MembershipStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class InvitationStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
class OrganizationRole(StrEnum):
    """Default role profiles. Kept deliberately small to avoid role explosion."""

    # Customer organization
    CUSTOMER_OWNER = "CUSTOMER_OWNER"
    CUSTOMER_ASSISTANT = "CUSTOMER_ASSISTANT"
    # Operator organization
    OPERATOR_ADMIN = "OPERATOR_ADMIN"
    OPERATOR_SALES = "OPERATOR_SALES"
    OPERATOR_OPERATIONS = "OPERATOR_OPERATIONS"
    OPERATOR_FINANCE = "OPERATOR_FINANCE"
    OPERATOR_COMPLIANCE = "OPERATOR_COMPLIANCE"
    # Platform (Sky Bridge Jet internal) organization
    PLATFORM_ADMIN = "PLATFORM_ADMIN"
    PLATFORM_COMPLIANCE_REVIEWER = "PLATFORM_COMPLIANCE_REVIEWER"
    PLATFORM_FINANCE_REVIEWER = "PLATFORM_FINANCE_REVIEWER"
    PLATFORM_SUPPORT = "PLATFORM_SUPPORT"
    PRODUCT_OWNER = "PRODUCT_OWNER"


# Which roles are assignable within each organization type. Prevents assigning,
# say, a PLATFORM role inside a CUSTOMER organization.
ROLES_BY_ORG_TYPE: Final[dict[OrganizationType, frozenset[OrganizationRole]]] = {
    OrganizationType.CUSTOMER: frozenset(
        {OrganizationRole.CUSTOMER_OWNER, OrganizationRole.CUSTOMER_ASSISTANT}
    ),
    OrganizationType.OPERATOR: frozenset(
        {
            OrganizationRole.OPERATOR_ADMIN,
            OrganizationRole.OPERATOR_SALES,
            OrganizationRole.OPERATOR_OPERATIONS,
            OrganizationRole.OPERATOR_FINANCE,
            OrganizationRole.OPERATOR_COMPLIANCE,
        }
    ),
    OrganizationType.PLATFORM: frozenset(
        {
            OrganizationRole.PLATFORM_ADMIN,
            OrganizationRole.PLATFORM_COMPLIANCE_REVIEWER,
            OrganizationRole.PLATFORM_FINANCE_REVIEWER,
            OrganizationRole.PLATFORM_SUPPORT,
            OrganizationRole.PRODUCT_OWNER,
        }
    ),
}

# The role(s) that administer membership within an organization type.
ADMIN_ROLE_BY_ORG_TYPE: Final[dict[OrganizationType, OrganizationRole]] = {
    OrganizationType.CUSTOMER: OrganizationRole.CUSTOMER_OWNER,
    OrganizationType.OPERATOR: OrganizationRole.OPERATOR_ADMIN,
    OrganizationType.PLATFORM: OrganizationRole.PLATFORM_ADMIN,
}


# --------------------------------------------------------------------------- #
# Permissions
# --------------------------------------------------------------------------- #
class Permission(StrEnum):
    """Stable capability vocabulary. Authorization is expressed only in these."""

    # Customer-facing
    CUSTOMER_READ = "customer.read"
    CUSTOMER_WRITE = "customer.write"
    TRIP_READ = "trip.read"
    TRIP_WRITE = "trip.write"
    BOOKING_READ = "booking.read"
    OFFER_READ = "offer.read"
    PAYMENT_READ = "payment.read"
    PAYMENT_INITIATE = "payment.initiate"
    PAYMENT_REFUND = "payment.refund"
    # Internal/trusted payment operations (create/authorize/capture/void). Additive,
    # platform-only capability introduced in Phase 9.0.A-3; distinct from the
    # high-consequence refund capability (payment.refund), which is unchanged.
    PAYMENT_OPERATE = "payment.operate"
    # Operator-facing
    OPERATOR_READ = "operator.read"
    OPERATOR_MANAGE = "operator.manage"
    OFFER_MANAGE = "offer.manage"
    BOOKING_DECIDE = "booking.decide"
    COMPLIANCE_EVIDENCE_SUBMIT = "compliance.evidence.submit"
    FINANCIAL_ONBOARDING_READ = "financial_onboarding.read"
    FINANCIAL_ONBOARDING_MANAGE = "financial_onboarding.manage"
    # Platform review (high-consequence)
    COMPLIANCE_REVIEW = "compliance.review"
    FINANCE_REVIEW = "finance.review"
    # Platform administration
    ADMIN_USERS_MANAGE = "admin.users.manage"
    ADMIN_ORGANIZATIONS_MANAGE = "admin.organizations.manage"
    # Organization self-administration (membership within one's own org)
    ORG_MEMBERSHIP_MANAGE = "org.membership.manage"


_CUSTOMER_ASSISTANT_PERMS: Final[frozenset[Permission]] = frozenset(
    {
        Permission.CUSTOMER_READ,
        Permission.TRIP_READ,
        Permission.TRIP_WRITE,
        Permission.OFFER_READ,
        Permission.BOOKING_READ,
        Permission.PAYMENT_READ,
        Permission.PAYMENT_INITIATE,
    }
)
_CUSTOMER_OWNER_PERMS: Final[frozenset[Permission]] = _CUSTOMER_ASSISTANT_PERMS | {
    Permission.CUSTOMER_WRITE,
    Permission.ORG_MEMBERSHIP_MANAGE,
}

_OPERATOR_BASE_PERMS: Final[frozenset[Permission]] = frozenset(
    {Permission.OPERATOR_READ, Permission.OFFER_READ, Permission.BOOKING_READ}
)

# The permission matrix. Every role maps to an explicit, testable permission set.
ROLE_PERMISSIONS: Final[dict[OrganizationRole, frozenset[Permission]]] = {
    OrganizationRole.CUSTOMER_OWNER: _CUSTOMER_OWNER_PERMS,
    OrganizationRole.CUSTOMER_ASSISTANT: _CUSTOMER_ASSISTANT_PERMS,
    OrganizationRole.OPERATOR_ADMIN: _OPERATOR_BASE_PERMS
    | {
        Permission.OPERATOR_MANAGE,
        Permission.OFFER_MANAGE,
        Permission.BOOKING_DECIDE,
        Permission.COMPLIANCE_EVIDENCE_SUBMIT,
        Permission.FINANCIAL_ONBOARDING_READ,
        Permission.FINANCIAL_ONBOARDING_MANAGE,
        Permission.PAYMENT_READ,
        Permission.ORG_MEMBERSHIP_MANAGE,
    },
    OrganizationRole.OPERATOR_SALES: _OPERATOR_BASE_PERMS | {Permission.OFFER_MANAGE},
    OrganizationRole.OPERATOR_OPERATIONS: _OPERATOR_BASE_PERMS | {Permission.BOOKING_DECIDE},
    OrganizationRole.OPERATOR_FINANCE: _OPERATOR_BASE_PERMS
    | {
        Permission.FINANCIAL_ONBOARDING_READ,
        Permission.FINANCIAL_ONBOARDING_MANAGE,
        Permission.PAYMENT_READ,
    },
    OrganizationRole.OPERATOR_COMPLIANCE: _OPERATOR_BASE_PERMS
    | {Permission.COMPLIANCE_EVIDENCE_SUBMIT},
    # Platform roles. Least privilege — reviewers do not get admin management.
    OrganizationRole.PLATFORM_SUPPORT: frozenset(
        {
            Permission.CUSTOMER_READ,
            Permission.OPERATOR_READ,
            Permission.BOOKING_READ,
            Permission.PAYMENT_READ,
        }
    ),
    OrganizationRole.PLATFORM_COMPLIANCE_REVIEWER: frozenset(
        {Permission.OPERATOR_READ, Permission.COMPLIANCE_REVIEW}
    ),
    # Read-only finance reviewer (Phase 9.0.A-3 B1/B2): payment.read for visibility and
    # finance.review, but NO payment mutation capability — neither payment.operate nor
    # payment.refund. (Phase 8 granted payment.refund here; ADR-043 corrects that to keep
    # the role strictly read-only, per the Product Owner decision.)
    OrganizationRole.PLATFORM_FINANCE_REVIEWER: frozenset(
        {
            Permission.OPERATOR_READ,
            Permission.PAYMENT_READ,
            Permission.FINANCE_REVIEW,
            Permission.FINANCIAL_ONBOARDING_READ,
        }
    ),
    OrganizationRole.PLATFORM_ADMIN: frozenset(
        {
            Permission.ADMIN_USERS_MANAGE,
            Permission.ADMIN_ORGANIZATIONS_MANAGE,
            Permission.ORG_MEMBERSHIP_MANAGE,
            Permission.CUSTOMER_READ,
            Permission.OPERATOR_READ,
            Permission.BOOKING_READ,
            Permission.PAYMENT_READ,
            Permission.PAYMENT_REFUND,
            Permission.PAYMENT_OPERATE,
            Permission.COMPLIANCE_REVIEW,
            Permission.FINANCE_REVIEW,
            Permission.FINANCIAL_ONBOARDING_READ,
            Permission.FINANCIAL_ONBOARDING_MANAGE,
        }
    ),
    # PRODUCT_OWNER is the single, documented, audited high-privilege role. It is a
    # superset of platform capabilities — not a hidden bypass scattered in code.
    OrganizationRole.PRODUCT_OWNER: frozenset(Permission),
}


def permissions_for_role(role: OrganizationRole) -> frozenset[Permission]:
    return ROLE_PERMISSIONS[role]


def role_is_valid_for_org_type(role: OrganizationRole, org_type: OrganizationType) -> bool:
    return role in ROLES_BY_ORG_TYPE[org_type]


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class IamError(DomainError):
    code = "iam_error"


class AuthenticationError(IamError):
    """Authentication failed or is required. Rendered as 401 with no detail leak."""

    code = "authentication_required"


class AuthorizationError(IamError):
    """The authenticated principal is not permitted. Rendered as 403."""

    code = "authorization_denied"


class IamConflictError(IamError):
    """A safe 409 conflict (e.g. duplicate email, last-admin protection)."""

    code = "iam_conflict"


class EmailAlreadyRegisteredError(IamConflictError):
    code = "email_already_registered"


class InvalidTokenError(IamError):
    """A verification/reset/invitation token is invalid, expired, or already used."""

    code = "invalid_token"


class LastAdminError(IamConflictError):
    code = "last_admin_protection"


class PrivilegeEscalationError(AuthorizationError):
    code = "privilege_escalation_denied"


class RateLimitedError(IamError):
    code = "rate_limited"


# --------------------------------------------------------------------------- #
# Value objects / validation
# --------------------------------------------------------------------------- #
_EMAIL_PATTERN: Final = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MIN_PASSWORD_LENGTH: Final = 12
_MAX_PASSWORD_LENGTH: Final = 200  # bound input; argon2 handles arbitrary length


def normalize_email(value: str) -> str:
    """Case-normalize an email for uniqueness without altering the stored display."""
    normalized = value.strip().lower()
    if not _EMAIL_PATTERN.fullmatch(normalized):
        raise IamError("A valid email address is required")
    return normalized


def validate_password(value: str) -> str:
    """Sensible password policy. The raw value is never logged or echoed."""
    if not _MIN_PASSWORD_LENGTH <= len(value) <= _MAX_PASSWORD_LENGTH:
        raise IamError(
            f"Password must be between {_MIN_PASSWORD_LENGTH} and {_MAX_PASSWORD_LENGTH} characters"
        )
    if value.strip() == "" or value.lower() == value or value.upper() == value:
        # Require at least mixed case as a minimal complexity floor.
        raise IamError("Password must include upper and lower case characters")
    return value
