# ADR-037: Authentication, sessions, and recovery

## Status

Accepted — passkeys/WebAuthn and MFA are designed-for future boundaries, not
implemented in Phase 8

## Context

Phase 8 needs a production-capable authentication foundation without inventing
cryptography, and it must keep working in tests and local development while staying
secure in production.

## Decision

- **Passwords** are hashed with **Argon2id** via `argon2-cffi`. We never implement
  hashing; the library owns hashing, constant-time verification, and rehash
  decisions. Plaintext is never stored or logged. A minimal complexity policy
  applies.
- **Sessions** are server-side and opaque. A high-entropy token is issued to the
  client; only its **SHA-256 hash** is persisted (`user_sessions.token_hash`), so a
  database disclosure yields no reusable credential. Sessions expire, can be revoked
  individually (logout) and en masse (logout-all), and a suspended/disabled user's
  sessions stop authenticating immediately (resolution re-checks user status).
- **Cookies**: the session token is an `HttpOnly` cookie with `SameSite=Lax` and a
  bounded lifetime. `Secure` is on in production (and the settings validator forbids
  disabling it there); development/test serve over plain http so it is off there.
  Tokens are never placed in `localStorage`.
- **CSRF**: a per-session CSRF secret is issued at login. State-changing (unsafe)
  requests must echo it in an `X-CSRF-Token` header, validated server-side against
  the session's stored secret — so `SameSite` is not the only defense.
- **Email verification** and **password reset** use single-use, expiring tokens
  stored only as hashes; tokens are never logged. Reset invalidates all existing
  sessions. Reset initiation is enumeration-safe (identical response whether or not
  the email exists); login returns a single generic error and equalizes timing with
  a dummy hash verification.
- **Recovery/notifications**: no email provider is integrated in Phase 8; tokens are
  surfaced in responses only outside production so tests/local flows complete, and
  the delivery boundary is deferred to a Notification phase.

## Consequences

The identity core is standards-based and safe to operate. WebAuthn/passkeys and MFA
can be added behind the same `User`/session model (documented future boundaries);
production internal/admin roles should require stronger authentication when MFA
lands. TOTP secrets, if added, must be stored hashed/encrypted — not casually.
