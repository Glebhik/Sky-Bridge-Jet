from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from sky_bridge_jet.modules.iam.domain import (
    OrganizationRole,
    OrganizationType,
    UserStatus,
)

# Email is validated/normalized by the domain (normalize_email); the schema only
# bounds length. This avoids a separate email-validator dependency.
EmailStr = Annotated[str, Field(min_length=3, max_length=320)]
Password = Annotated[str, Field(min_length=12, max_length=200)]
Token = Annotated[str, Field(min_length=16, max_length=512)]


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# -- Auth --------------------------------------------------------------------
class RegisterRequest(ApiModel):
    email: EmailStr
    password: Password
    display_name: str | None = Field(default=None, max_length=200)


class LoginRequest(ApiModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=200)]


class VerifyEmailRequest(ApiModel):
    token: Token


class ResendVerificationRequest(ApiModel):
    email: EmailStr


class PasswordResetRequest(ApiModel):
    email: EmailStr


class PasswordResetConfirm(ApiModel):
    token: Token
    password: Password


class AcceptInvitationRequest(ApiModel):
    token: Token


class UserResponse(ApiModel):
    id: UUID
    email: str
    display_name: str | None
    status: UserStatus
    email_verified_at: datetime | None
    created_at: datetime


class MembershipView(ApiModel):
    organization_id: UUID
    organization_type: OrganizationType
    role: OrganizationRole


class MeResponse(ApiModel):
    user: UserResponse
    memberships: list[MembershipView]
    permissions: list[str]


class LoginResponse(ApiModel):
    user: UserResponse
    # The CSRF token the browser must echo in X-CSRF-Token for unsafe requests.
    csrf_token: str


class MessageResponse(ApiModel):
    message: str


# -- Development-only token surfacing ----------------------------------------
class RegistrationResponse(ApiModel):
    """Registration acknowledgement.

    ``verification_token`` is surfaced only outside production (no email provider in
    Phase 8) so tests and local flows can complete verification. It is never returned
    in production and never logged.
    """

    user: UserResponse
    verification_token: str | None = None


# -- Organizations & membership ----------------------------------------------
class CreateOrganizationRequest(ApiModel):
    organization_type: OrganizationType
    display_name: str = Field(max_length=200)
    customer_id: UUID | None = None
    operator_id: UUID | None = None
    owner_user_id: UUID | None = None


class OrganizationResponse(ApiModel):
    id: UUID
    organization_type: OrganizationType
    display_name: str
    customer_id: UUID | None
    operator_id: UUID | None
    created_at: datetime


class InviteRequest(ApiModel):
    email: EmailStr
    role: OrganizationRole


class InvitationResponse(ApiModel):
    id: UUID
    organization_id: UUID
    role: OrganizationRole
    # Dev-only, like the verification token: lets tests accept without email.
    invitation_token: str | None = None


class MembershipResponse(ApiModel):
    id: UUID
    user_id: UUID
    organization_id: UUID
    role: OrganizationRole
    status: str
    created_at: datetime


class AccountRecoveryResponse(ApiModel):
    """Minimal, safe result of a successful customer-account recovery (ADR-047).

    Exposes only the identifiers the authenticated client needs to adopt its new
    personal customer context — never audit, membership-internal, or foreign-tenant
    detail. ``role`` is always ``CUSTOMER_OWNER`` and ``organization_type`` ``CUSTOMER``.
    """

    organization_id: UUID
    customer_id: UUID
    organization_type: OrganizationType
    role: OrganizationRole


class ChangeRoleRequest(ApiModel):
    role: OrganizationRole


class SetUserStatusRequest(ApiModel):
    status: UserStatus
