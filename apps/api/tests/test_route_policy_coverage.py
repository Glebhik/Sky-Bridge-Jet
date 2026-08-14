"""The authorization-policy coverage invariant (no DB required).

Fails if any registered route/method is unclassified, any classified route is not
registered, dispositions collide, or a protected route is accidentally public. This
is the guard that stops a route from silently becoming accessible.
"""

from __future__ import annotations

import pytest

from sky_bridge_jet.main import app
from sky_bridge_jet.modules.iam.dependencies import is_public_route
from sky_bridge_jet.modules.route_policy import (
    DOCUMENTATION_ROUTES,
    ROUTE_POLICIES,
    Disposition,
    coverage_report,
    enumerate_app_routes,
    policy_index,
)


def test_verified_route_counts() -> None:
    registered = enumerate_app_routes(app)
    assert len(registered) == 80, sorted(registered)
    openapi_ops = {r for r in registered if r[1] not in DOCUMENTATION_ROUTES}
    assert len(openapi_ops) == 76


def test_every_route_has_exactly_one_disposition() -> None:
    # policy_index() raises on duplicates; also assert one entry per policy.
    index = policy_index()
    assert len(index) == len(ROUTE_POLICIES)


def test_full_coverage_no_gaps_or_extras() -> None:
    unclassified, not_registered = coverage_report(app)
    assert not unclassified, f"registered routes missing a policy: {sorted(unclassified)}"
    assert not not_registered, f"policies for non-existent routes: {sorted(not_registered)}"


def test_public_dispositions_match_the_authentication_gate() -> None:
    """A route is PUBLIC in the registry iff the gate treats it as public.

    This catches a protected route accidentally classified as public, and a public
    route that the gate would nonetheless force authentication on.
    """
    # App-level routes (the /api/v1 namespace root, health/ready, docs) are mounted
    # on the app, outside the versioned router's authentication gate.
    app_level = {*DOCUMENTATION_ROUTES, "/api/v1", "/health", "/ready"}
    for policy in ROUTE_POLICIES:
        if not policy.path.startswith("/api/v1/") or policy.path in app_level:
            continue  # only routes actually under the versioned gate are compared
        public_in_gate = is_public_route(policy.method, policy.path)
        public_in_registry = policy.disposition is Disposition.PUBLIC
        assert public_in_gate == public_in_registry, (
            f"{policy.method} {policy.path}: gate public={public_in_gate} "
            f"registry public={public_in_registry}"
        )


def test_no_versioned_pending_route_is_public() -> None:
    """Non-public dispositions must never be public — the global gate still applies."""
    protected = {
        Disposition.PHASE_9_0A_1_BOUND,
        Disposition.PHASE_9_0A_2_BOUND,
        Disposition.PHASE_9_0A_3_PENDING,
        Disposition.ALREADY_BOUND,
    }
    for policy in ROUTE_POLICIES:
        if policy.disposition in protected:
            assert not is_public_route(policy.method, policy.path), policy


def test_operator_chain_is_fully_bound_no_pending_remains() -> None:
    """Phase 9.0.A-2 binds every operator-chain route; nothing stays pending here."""
    index = policy_index()
    bound = [k for k, p in index.items() if p.disposition is Disposition.PHASE_9_0A_2_BOUND]
    assert len(bound) == 24, sorted(bound)
    # The 9.0.A-2-pending disposition no longer exists; 9.0.A-3 pending is untouched.
    assert not hasattr(Disposition, "PHASE_9_0A_2_PENDING")
    p3 = [k for k, p in index.items() if p.disposition is Disposition.PHASE_9_0A_3_PENDING]
    assert len(p3) == 6, sorted(p3)


def test_coverage_detects_an_unclassified_route() -> None:
    """Prove the invariant fails when a new route is not in the registry."""
    registered = enumerate_app_routes(app) | {("GET", "/api/v1/newly-added-route")}
    classified = set(policy_index().keys())
    unclassified = registered - classified
    assert ("GET", "/api/v1/newly-added-route") in unclassified


def test_duplicate_policy_is_rejected() -> None:
    from sky_bridge_jet.modules import route_policy

    dup = (*route_policy.ROUTE_POLICIES, route_policy.ROUTE_POLICIES[0])
    original = route_policy.ROUTE_POLICIES
    route_policy.ROUTE_POLICIES = dup  # type: ignore[misc]
    try:
        with pytest.raises(ValueError, match="Duplicate route policy"):
            route_policy.policy_index()
    finally:
        route_policy.ROUTE_POLICIES = original  # type: ignore[misc]
