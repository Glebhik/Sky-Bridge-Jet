"""Privacy-safe bounded operational aggregates for staging monitoring."""

# ruff: noqa: E501 -- one scalar subquery per line keeps the audited SQL legible.

from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from sky_bridge_jet.modules import access
from sky_bridge_jet.modules.iam.dependencies import (
    ActiveOrganization,
    CurrentPrincipal,
    DatabaseSession,
)
from sky_bridge_jet.modules.iam.domain import Permission

router = APIRouter(prefix="/platform/operations", tags=["platform-operations"])


@router.get("/diagnostics", operation_id="getOperationalDiagnostics")
def diagnostics(
    principal: CurrentPrincipal,
    active_organization: ActiveOrganization,
    session: DatabaseSession,
) -> dict[str, Any]:
    """One bounded SQL aggregate; no user/resource identifiers or high-cardinality labels."""
    access.active_platform_organization_id(
        principal, active_organization, Permission.OPERATIONS_DIAGNOSTICS_READ
    )
    row = (
        session.execute(
            text(
                """
            SELECT
              (SELECT count(*) FROM payment_operations WHERE result = 'UNKNOWN') AS payment_unknown,
              (SELECT extract(epoch FROM (now() - min(created_at)))::bigint
                 FROM payment_operations WHERE result = 'UNKNOWN') AS payment_unknown_oldest_seconds,
              (SELECT count(*) FROM notification_outbox WHERE delivery_state = 'PENDING') AS outbox_pending,
              (SELECT extract(epoch FROM (now() - min(created_at)))::bigint
                 FROM notification_outbox
                WHERE delivery_state IN ('PENDING','FAILED_RETRYABLE')) AS outbox_oldest_due_seconds,
              (SELECT count(*) FROM notification_outbox WHERE delivery_state = 'FAILED_RETRYABLE') AS outbox_retryable,
              (SELECT count(*) FROM notification_outbox WHERE delivery_state = 'FAILED_PERMANENT') AS outbox_permanent,
              (SELECT count(*) FROM notification_outbox
                 WHERE delivery_state = 'CLAIMED' AND claimed_at < now() - interval '10 minutes') AS outbox_expired_claims,
              (SELECT count(*) FROM operator_admissions WHERE status IN ('SUBMITTED','UNDER_REVIEW')) AS admissions_pending,
              (SELECT extract(epoch FROM (now() - min(created_at)))::bigint
                 FROM operator_admissions
                WHERE status IN ('SUBMITTED','UNDER_REVIEW')) AS admissions_oldest_seconds,
              (SELECT count(*) FROM compliance_evidence WHERE status IN ('SUBMITTED','UNDER_REVIEW')) AS evidence_pending,
              (SELECT extract(epoch FROM (now() - min(created_at)))::bigint
                 FROM compliance_evidence
                WHERE status IN ('SUBMITTED','UNDER_REVIEW')) AS evidence_oldest_seconds,
              (SELECT mode::text FROM pilot_governance_state LIMIT 1) AS pilot_mode,
              (SELECT payment_initiation_enabled FROM pilot_governance_state LIMIT 1) AS payment_initiation_enabled,
              (SELECT count(*) FROM pilot_participants WHERE status = 'ACTIVE') AS active_participants
            """
            )
        )
        .mappings()
        .one()
    )
    return {"status": "ok", "environment_safe": True, **dict(row)}
