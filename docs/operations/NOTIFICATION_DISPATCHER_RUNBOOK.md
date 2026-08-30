# Notification dispatcher runbook

Run as a separate process using the same release image and managed database:
`python -m sky_bridge_jet.modules.notifications.worker`. Use `--once` only from a controlled
scheduler. Secrets come from the platform secret manager. Validate 1..100 batch size, 1..3600
second poll, 0.5..30 second timeout, environment, provider and staging allowlist before start.
When `MARKETPLACE_EMAIL_ENABLED=false`, the worker performs a true no-op before any database
claim. Pending, due retryable and expired-claim work remains unchanged. Re-enable and restart to
resume from canonical durable state; disabled never means successful FAKE delivery.

Evidence of health is repeated bounded completion logs plus queue diagnostics: oldest due age,
pending, retryable, permanent and expired-claim counts. Alert when runs cease while due work
ages, a critical row becomes permanent, provider auth/config fails, complaints occur, or bounce
volume spikes. External alert routing remains a separate provisioning gate.

SIGTERM/SIGINT stops after the current bounded dispatch. A crash before send is recovered by
the existing ten-minute lease. A crash after provider acceptance may be retried with the same
logical idempotency key; review ambiguity rather than creating another intent. Multiple workers
are allowed: SKIP LOCKED and claim tokens prevent duplicate internal ownership/finalization.

During provider outage, stop hammering, preserve the queue, assess critical events for manual
fallback, pause new pilot journeys if communication is unsafe, restore configuration/provider,
restart one worker, review aged rows, then restore normal concurrency. PAUSED pilot mode does
not erase or automatically suppress existing critical intents. Pilot PAUSED controls journey
creation; the delivery switch controls provider sending. Neither deletes queued evidence.
