"""FastAPI authentication/authorization dependencies.

Routers depend on a trusted principal rather than parsing cookies/headers. The
principal is resolved from the session cookie; the active organization context is
validated against membership; permission enforcement is a small factory so routes
declare *what capability* they need, never a role string.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from sky_bridge_jet.core.config import Settings, get_settings
from sky_bridge_jet.db.session import SessionLocal, get_db
from sky_bridge_jet.modules.iam.authz import (
    Principal,
    ResourceScope,
    authorize,
)
from sky_bridge_jet.modules.iam.domain import (
    AuthenticationError,
    AuthorizationError,
    Permission,
)
from sky_bridge_jet.modules.iam.services import AuthService, load_principal

DatabaseSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]

# State-changing methods require CSRF defense when authenticated via cookie.
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_CSRF_HEADER = "x-csrf-token"

# Routes under /api/v1 reachable without a session. Everything else under the
# versioned router is authenticated (fail closed). Health/ready/openapi/docs and the
# /api/v1 root live on the app (outside this router) and are inherently public.
_PUBLIC_EXACT: frozenset[str] = frozenset(
    {
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/verify-email",
        # Enumeration-safe verification resend (Phase 9.2.A): a public initiation path,
        # like register/verify/password-reset.
        "/api/v1/auth/verification/resend",
        "/api/v1/auth/password-reset",
        "/api/v1/auth/password-reset/confirm",
        # The Stripe webhook authenticates by signature (not a session).
        "/api/v1/webhooks/stripe",
    }
)
# Public read-only discovery (product policy): the airport catalog.
_PUBLIC_GET_PREFIXES: tuple[str, ...] = ("/api/v1/airports",)


def is_public_route(method: str, path: str) -> bool:
    if path in _PUBLIC_EXACT:
        return True
    return method == "GET" and any(path.startswith(p) for p in _PUBLIC_GET_PREFIXES)


def _session_token(request: Request, settings: Settings) -> str | None:
    return request.cookies.get(settings.session_cookie_name)


def enforce_authentication(
    request: Request, session: DatabaseSession, settings: AppSettings
) -> None:
    """The global authentication gate, applied to the whole versioned router.

    Fail closed: every route is authenticated unless explicitly PUBLIC. Resolving on
    the request's own session (not a bespoke one) keeps tests able to override
    ``get_db``; the read transaction is rolled back afterward so the endpoint's write
    command opens its own clean transaction. The resolved principal is attached to
    ``request.state`` for reuse by route dependencies.
    """
    request.state.principal = None
    if is_public_route(request.method, request.url.path):
        return
    raw_token = _session_token(request, settings)
    if not raw_token:
        raise AuthenticationError("Authentication is required")
    try:
        resolved = AuthService(session, settings).authenticate_session(raw_token)
        if resolved is None:
            raise AuthenticationError("Authentication is required")
        user_session, user = resolved
        if request.method in _UNSAFE_METHODS:
            provided = request.headers.get(_CSRF_HEADER)
            if not provided or provided != user_session.csrf_token:
                raise AuthorizationError("Missing or invalid CSRF token")
        request.state.principal = load_principal(session, user, user_session.id)
    finally:
        # Release the autobegun read transaction so the endpoint's ``session.begin()``
        # starts cleanly on the shared request session.
        session.rollback()


def get_current_principal(request: Request, settings: AppSettings) -> Principal:
    """Return the principal resolved by :func:`enforce_authentication`.

    Falls back to a fresh-session resolution if state is missing (defense in depth,
    e.g. a route that depends on the principal without the router gate).
    """
    principal = getattr(request.state, "principal", None)
    if isinstance(principal, Principal):
        return principal
    raw_token = _session_token(request, settings)
    if not raw_token:
        raise AuthenticationError("Authentication is required")
    with SessionLocal() as auth_session:
        resolved = AuthService(auth_session, settings).authenticate_session(raw_token)
        if resolved is None:
            raise AuthenticationError("Authentication is required")
        user_session, user = resolved
        if request.method in _UNSAFE_METHODS:
            provided = request.headers.get(_CSRF_HEADER)
            if not provided or provided != user_session.csrf_token:
                raise AuthorizationError("Missing or invalid CSRF token")
        return load_principal(auth_session, user, user_session.id)


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]


def get_active_organization(
    principal: CurrentPrincipal,
    x_organization_id: Annotated[str | None, Header()] = None,
) -> UUID | None:
    """Validate an optional active-organization header against membership.

    An arbitrary ``X-Organization-Id`` is never trusted: it must match one of the
    principal's active memberships, else the request is rejected.
    """
    if x_organization_id is None:
        return None
    try:
        org_id = UUID(x_organization_id)
    except ValueError as error:
        raise AuthorizationError("Invalid organization context") from error
    if not any(m.organization_id == org_id for m in principal.memberships):
        raise AuthorizationError("You are not a member of that organization")
    return org_id


ActiveOrganization = Annotated[UUID | None, Depends(get_active_organization)]


def require_permission(permission: Permission) -> Any:
    """Dependency factory: require a global (non-tenant) permission.

    For resource-scoped checks, routers call :func:`sky_bridge_jet.modules.iam.authz.authorize`
    directly with the resolved :class:`ResourceScope` once the owning tenant is known.
    Returns a ``Depends`` marker suitable for a route's ``dependencies=[...]``.
    """

    def _dependency(principal: CurrentPrincipal) -> Principal:
        authorize(principal, permission, ResourceScope.global_())
        return principal

    return Depends(_dependency)
