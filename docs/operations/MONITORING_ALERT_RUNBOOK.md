# Monitoring and Alert Runbook

Signals are provider-neutral logs/aggregates: readiness and migration mismatch; DB
availability; 5xx rate; UNKNOWN payment count/oldest age; outbox pending, retry,
permanent-failure and expired-claim count/age; pending compliance queues; pilot mode,
payment switch and participant counts; privileged-auth anomaly; backup/restore failure;
staging safety violation. Queries must aggregate in SQL and emit no PII or resource IDs.

Thresholds are configurable staging rehearsal values, not contractual SLAs. Operations
owns notification alerts, finance owns payment exceptions, compliance owns review aging,
and the pilot/support owner coordinates incidents with backups. Until an external alert
provider is selected, inspect the signals during named pilot windows and execute manual
phone/email escalation. External delivery remains `PROVIDER-BLOCKED`.
