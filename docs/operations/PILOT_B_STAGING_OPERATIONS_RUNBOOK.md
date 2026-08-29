# Pilot B Staging Operations Runbook

## Release and GO

Record exact SHA and green CI. Confirm isolated HTTPS staging, Auth0 staging app, test or
fake payments, synthetic data and **NO REAL MONEY**. Take the managed backup/PITR
checkpoint, review revision 0014, and let exactly one migration owner/job run Alembic.
Deploy API, require `/health` and `/ready`, deploy Web, run customer/operator/platform
smokes, verify `CONTROLLED_EXTERNAL`, monitoring and named owners, then record GO.

## Monitor

Watch readiness/5xx, UNKNOWN payments, notification retry/permanent failure aging,
compliance queue aging, privileged-auth anomalies and backup/restore-test status. Use the
approved manual escalation paths until an alert provider is selected.

## Pause and incident

Set Pilot mode `PAUSED`, disable payment initiation when relevant, preserve the existing
compliance/payment recovery control plane and evidence, investigate and record the
incident. Categories include tenant/privacy, duplicate financial action, UNKNOWN,
compliance bypass, notification outage, DB integrity/recovery, unexpected financial
action, privileged compromise, availability and IdP outage. Resume only on documented GO.

## Rollback

Roll back the application only when schema-compatible. Never auto-downgrade. Downgrade
requires data-safety review; prefer a forward fix where downgrade risks data. Recheck
readiness and all smoke tests.

