from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse

from sky_bridge_jet.modules.core_aviation.schemas import ErrorResponse
from sky_bridge_jet.modules.iam.dependencies import (
    AppSettings,
    CurrentPrincipal,
    DatabaseSession,
    require_permission,
)
from sky_bridge_jet.modules.iam.domain import (
    AuthenticationError,
    AuthorizationError,
    IamConflictError,
    IamError,
    InvalidTokenError,
    OrganizationRole,
    OrganizationType,
    Permission,
    RateLimitedError,
)
from sky_bridge_jet.modules.iam.provisioning import recover_personal_customer
from sky_bridge_jet.modules.iam.ratelimit import RateLimiter
from sky_bridge_jet.modules.iam.schemas import (
    AcceptInvitationRequest,
    AccountRecoveryResponse,
    ChangeRoleRequest,
    CreateOrganizationRequest,
    InvitationResponse,
    InviteRequest,
    LoginRequest,
    LoginResponse,
    MembershipResponse,
    MembershipView,
    MeResponse,
    MessageResponse,
    OrganizationResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    RegisterRequest,
    RegistrationResponse,
    SetUserStatusRequest,
    UserResponse,
    VerifyEmailRequest,
)
from sky_bridge_jet.modules.iam.services import AuthService, OrganizationService

router = APIRouter(tags=["iam"])
_ERR = {"model": ErrorResponse}

_login_limiter = RateLimiter(max_attempts=10, window_seconds=60)
_reset_limiter = RateLimiter(max_attempts=5, window_seconds=60)
# Account recovery is a rare, authenticated, tenant-creating action; keep the floor low.
_recover_limiter = RateLimiter(max_attempts=5, window_seconds=60)


def _client_key(request: Request, suffix: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{host}:{suffix}"


def _dev_token(settings: AppSettings, token: str) -> str | None:
    """Surface verification/invite tokens only outside production (no mailer yet)."""
    return token if settings.app_environment != "production" else None


def _set_session_cookies(
    response: Response, settings: AppSettings, *, session_token: str, csrf_token: str
) -> None:
    secure = settings.cookie_secure_effective
    max_age = settings.session_ttl_seconds
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
        max_age=max_age,
    )
    # Readable CSRF cookie (double-submit convenience); validation is server-side
    # against the session's stored secret, so SameSite is not the only defense.
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf_token,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
        max_age=max_age,
    )


def _clear_session_cookies(response: Response, settings: AppSettings) -> None:
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")


# --------------------------------------------------------------------------- #
# Exception handlers (safe envelopes)
# --------------------------------------------------------------------------- #
def _safe_error(request: Request, *, status_code: int, code: str, message: str) -> JSONResponse:
    response = JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": None}},
    )
    correlation_id = getattr(request.state, "correlation_id", None)
    if correlation_id is not None:
        response.headers["X-Request-ID"] = correlation_id
    return response


def register_iam_exception_handlers(app: object) -> None:
    from fastapi import FastAPI

    if not isinstance(app, FastAPI):
        raise TypeError("Expected a FastAPI application")

    @app.exception_handler(AuthenticationError)
    async def _auth_required(request: Request, error: AuthenticationError) -> JSONResponse:
        return _safe_error(
            request, status_code=status.HTTP_401_UNAUTHORIZED, code=error.code, message=str(error)
        )

    @app.exception_handler(AuthorizationError)
    async def _forbidden(request: Request, error: AuthorizationError) -> JSONResponse:
        return _safe_error(
            request, status_code=status.HTTP_403_FORBIDDEN, code=error.code, message=str(error)
        )

    @app.exception_handler(IamConflictError)
    async def _conflict(request: Request, error: IamConflictError) -> JSONResponse:
        return _safe_error(
            request, status_code=status.HTTP_409_CONFLICT, code=error.code, message=str(error)
        )

    @app.exception_handler(RateLimitedError)
    async def _rate_limited(request: Request, error: RateLimitedError) -> JSONResponse:
        return _safe_error(
            request,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code=error.code,
            message=str(error),
        )

    @app.exception_handler(InvalidTokenError)
    async def _invalid_token(request: Request, error: InvalidTokenError) -> JSONResponse:
        return _safe_error(
            request, status_code=status.HTTP_400_BAD_REQUEST, code=error.code, message=str(error)
        )

    @app.exception_handler(IamError)
    async def _iam_error(request: Request, error: IamError) -> JSONResponse:
        return _safe_error(
            request, status_code=status.HTTP_400_BAD_REQUEST, code=error.code, message=str(error)
        )


# --------------------------------------------------------------------------- #
# Authentication (public)
# --------------------------------------------------------------------------- #
@router.post(
    "/auth/register",
    response_model=RegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={409: _ERR, 400: _ERR},
    operation_id="registerUser",
)
def register(
    data: RegisterRequest, session: DatabaseSession, settings: AppSettings
) -> RegistrationResponse:
    user, token = AuthService(session, settings).register(
        email=data.email, password=data.password, display_name=data.display_name
    )
    return RegistrationResponse(
        user=UserResponse.model_validate(user), verification_token=_dev_token(settings, token)
    )


@router.post(
    "/auth/verify-email",
    response_model=UserResponse,
    responses={400: _ERR},
    operation_id="verifyEmail",
)
def verify_email(
    data: VerifyEmailRequest, session: DatabaseSession, settings: AppSettings
) -> UserResponse:
    user = AuthService(session, settings).verify_email(data.token)
    return UserResponse.model_validate(user)


@router.post(
    "/auth/login",
    response_model=LoginResponse,
    responses={401: _ERR, 429: _ERR},
    operation_id="login",
)
def login(
    data: LoginRequest,
    request: Request,
    response: Response,
    session: DatabaseSession,
    settings: AppSettings,
) -> LoginResponse:
    if not _login_limiter.check(_client_key(request, f"login:{data.email.strip().lower()}")):
        raise RateLimitedError("Too many login attempts; please try again shortly")
    user_session, raw_token, csrf = AuthService(session, settings).login(
        email=data.email, password=data.password
    )
    user = AuthService(session, settings).users.get(user_session.user_id)
    assert user is not None
    _set_session_cookies(response, settings, session_token=raw_token, csrf_token=csrf)
    return LoginResponse(user=UserResponse.model_validate(user), csrf_token=csrf)


@router.post(
    "/auth/logout",
    response_model=MessageResponse,
    responses={401: _ERR},
    operation_id="logout",
)
def logout(
    principal: CurrentPrincipal, response: Response, session: DatabaseSession, settings: AppSettings
) -> MessageResponse:
    AuthService(session, settings).logout(principal.session_id)
    _clear_session_cookies(response, settings)
    return MessageResponse(message="Signed out")


@router.post(
    "/auth/logout-all",
    response_model=MessageResponse,
    responses={401: _ERR},
    operation_id="logoutAll",
)
def logout_all(
    principal: CurrentPrincipal, response: Response, session: DatabaseSession, settings: AppSettings
) -> MessageResponse:
    AuthService(session, settings).logout_all(principal.user_id)
    _clear_session_cookies(response, settings)
    return MessageResponse(message="All sessions revoked")


@router.get("/auth/me", response_model=MeResponse, responses={401: _ERR}, operation_id="getMe")
def me(principal: CurrentPrincipal, session: DatabaseSession, settings: AppSettings) -> MeResponse:
    user = AuthService(session, settings).users.get(principal.user_id)
    assert user is not None
    memberships = [
        MembershipView(
            organization_id=m.organization_id,
            organization_type=m.organization_type,
            role=m.role,
        )
        for m in principal.memberships
    ]
    return MeResponse(
        user=UserResponse.model_validate(user),
        memberships=memberships,
        permissions=sorted(p.value for p in principal.all_permissions()),
    )


@router.post(
    "/auth/password-reset",
    response_model=MessageResponse,
    responses={429: _ERR},
    operation_id="requestPasswordReset",
)
def request_password_reset(
    data: PasswordResetRequest, request: Request, session: DatabaseSession, settings: AppSettings
) -> MessageResponse:
    if not _reset_limiter.check(_client_key(request, "reset")):
        raise RateLimitedError("Too many reset requests; please try again shortly")
    # Enumeration-safe: identical response whether or not the email is registered.
    AuthService(session, settings).request_password_reset(data.email)
    return MessageResponse(message="If the account exists, a reset link has been sent")


@router.post(
    "/auth/password-reset/confirm",
    response_model=MessageResponse,
    responses={400: _ERR},
    operation_id="confirmPasswordReset",
)
def confirm_password_reset(
    data: PasswordResetConfirm, session: DatabaseSession, settings: AppSettings
) -> MessageResponse:
    AuthService(session, settings).reset_password(data.token, data.password)
    return MessageResponse(message="Password updated")


# --------------------------------------------------------------------------- #
# Invitations (authenticated)
# --------------------------------------------------------------------------- #
@router.post(
    "/auth/invitations/accept",
    response_model=MembershipResponse,
    responses={400: _ERR, 401: _ERR, 409: _ERR},
    operation_id="acceptInvitation",
)
def accept_invitation(
    data: AcceptInvitationRequest,
    principal: CurrentPrincipal,
    session: DatabaseSession,
    settings: AppSettings,
) -> MembershipResponse:
    membership = OrganizationService(session, settings).accept_invitation(
        principal.user_id, data.token
    )
    return MembershipResponse.model_validate(membership)


# --------------------------------------------------------------------------- #
# Customer-account recovery (authenticated self-service, Phase 9.1.A)
# --------------------------------------------------------------------------- #
@router.post(
    "/auth/customer-account/recover",
    response_model=AccountRecoveryResponse,
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 409: _ERR, 429: _ERR},
    operation_id="recoverCustomerAccount",
)
def recover_customer_account(
    request: Request,
    principal: CurrentPrincipal,
    session: DatabaseSession,
) -> AccountRecoveryResponse:
    """Provision a personal customer tenant for an authenticated, stranded user.

    Authentication and CSRF are enforced by the global gate (this is a non-public POST).
    The caller supplies no body and no ownership identifiers: identity is the session
    principal, and the tenant is created server-side (INDIVIDUAL customer, CUSTOMER
    organization, CUSTOMER_OWNER membership) by the single shared provisioning path,
    under a canonical user-row lock. Eligibility/denial and concurrency live in
    :func:`recover_personal_customer`.
    """
    if not _recover_limiter.check(_client_key(request, f"recover:{principal.user_id}")):
        raise RateLimitedError("Too many recovery attempts; please try again shortly")
    organization = recover_personal_customer(session, principal.user_id)
    assert organization.customer_id is not None  # a CUSTOMER org always links a customer
    return AccountRecoveryResponse(
        organization_id=organization.id,
        customer_id=organization.customer_id,
        organization_type=OrganizationType.CUSTOMER,
        role=OrganizationRole.CUSTOMER_OWNER,
    )


# --------------------------------------------------------------------------- #
# Organizations & membership administration
# --------------------------------------------------------------------------- #
@router.post(
    "/organizations",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR},
    operation_id="createOrganization",
    dependencies=[require_permission(Permission.ADMIN_ORGANIZATIONS_MANAGE)],
)
def create_organization(
    data: CreateOrganizationRequest, session: DatabaseSession, settings: AppSettings
) -> OrganizationResponse:
    org = OrganizationService(session, settings).create_organization(
        organization_type=data.organization_type,
        display_name=data.display_name,
        customer_id=data.customer_id,
        operator_id=data.operator_id,
        owner_user_id=data.owner_user_id,
    )
    return OrganizationResponse.model_validate(org)


@router.post(
    "/organizations/{organization_id}/invitations",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: _ERR, 401: _ERR, 403: _ERR},
    operation_id="createInvitation",
)
def create_invitation(
    organization_id: UUID,
    data: InviteRequest,
    principal: CurrentPrincipal,
    session: DatabaseSession,
    settings: AppSettings,
) -> InvitationResponse:
    invitation, token = OrganizationService(session, settings).invite(
        principal, organization_id=organization_id, email=data.email, role=data.role
    )
    return InvitationResponse(
        id=invitation.id,
        organization_id=invitation.organization_id,
        role=invitation.role,
        invitation_token=_dev_token(settings, token),
    )


@router.get(
    "/organizations/{organization_id}/members",
    response_model=list[MembershipResponse],
    responses={401: _ERR, 403: _ERR},
    operation_id="listOrganizationMembers",
)
def list_members(
    organization_id: UUID,
    principal: CurrentPrincipal,
    session: DatabaseSession,
    settings: AppSettings,
) -> list[MembershipResponse]:
    members = OrganizationService(session, settings).list_members(principal, organization_id)
    return [MembershipResponse.model_validate(m) for m in members]


@router.post(
    "/organizations/{organization_id}/members/{membership_id}/role",
    response_model=MembershipResponse,
    responses={400: _ERR, 401: _ERR, 403: _ERR, 409: _ERR},
    operation_id="changeMemberRole",
)
def change_member_role(
    organization_id: UUID,
    membership_id: UUID,
    data: ChangeRoleRequest,
    principal: CurrentPrincipal,
    session: DatabaseSession,
    settings: AppSettings,
) -> MembershipResponse:
    membership = OrganizationService(session, settings).change_role(
        principal, membership_id=membership_id, new_role=data.role
    )
    return MembershipResponse.model_validate(membership)


@router.delete(
    "/organizations/{organization_id}/members/{membership_id}",
    response_model=MembershipResponse,
    responses={400: _ERR, 401: _ERR, 403: _ERR, 409: _ERR},
    operation_id="revokeMembership",
)
def revoke_membership(
    organization_id: UUID,
    membership_id: UUID,
    principal: CurrentPrincipal,
    session: DatabaseSession,
    settings: AppSettings,
) -> MembershipResponse:
    membership = OrganizationService(session, settings).revoke_membership(
        principal, membership_id=membership_id
    )
    return MembershipResponse.model_validate(membership)


# --------------------------------------------------------------------------- #
# Platform user administration
# --------------------------------------------------------------------------- #
@router.post(
    "/admin/users/{user_id}/status",
    response_model=UserResponse,
    responses={401: _ERR, 403: _ERR},
    operation_id="setUserStatus",
    dependencies=[require_permission(Permission.ADMIN_USERS_MANAGE)],
)
def set_user_status(
    user_id: UUID,
    data: SetUserStatusRequest,
    session: DatabaseSession,
    settings: AppSettings,
) -> UserResponse:
    user = AuthService(session, settings).set_user_status(user_id, data.status)
    return UserResponse.model_validate(user)
