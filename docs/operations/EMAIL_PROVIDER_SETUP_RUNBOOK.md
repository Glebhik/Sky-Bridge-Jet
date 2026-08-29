# Resend marketplace-email setup

Create separate staging and production resources where supported. Configure API keys and Svix
webhook signing secrets only in the secret manager; never Web configuration or repository files.
Configure a server-owned From address and optional fixed support Reply-To. Enable marketplace
email explicitly only after configuration validation.

Before staging: configure an approved-recipient allowlist, register the exact HTTPS webhook,
send one canonical internal test intent, confirm provider acceptance/message correlation and a
signed delivery or bounce event, then exercise a provider-supported bounce/complaint simulator.

Before production: verify sending domain, SPF, DKIM, DMARC policy/alignment, return path,
suppression and complaint handling, provider limits/quota, sender reputation monitoring and
privacy/DPA review. None is READY merely because code exists.

For key rotation, operations creates a new restricted key/secret, installs it in staging,
verifies one approved rehearsal, promotes through change control, verifies production health,
then revokes the old value. Rotate webhook secrets with an overlap procedure supported by the
provider or a controlled endpoint cutover; never log either value.
