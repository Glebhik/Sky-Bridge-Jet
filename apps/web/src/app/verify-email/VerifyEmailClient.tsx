"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { portalApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { ResendVerificationForm } from "@/components/auth/ResendVerificationForm";
import { Alert, Button, LoadingState } from "@/components/ui/primitives";

/**
 * Client-side consumer of the emailed verification link `/verify-email#token=<raw-token>`
 * (Phase 9.2.B2.2).
 *
 * Security-critical sequence, in this exact order:
 *   1. read the token strictly from the URL fragment (never a query string);
 *   2. IMMEDIATELY strip the fragment from the visible URL/history (replaceState) — before
 *      any network call, so the raw token is never in the address bar during the request;
 *   3. POST the token through the same-origin proxy (portalApi.verifyEmail);
 *   4. discard the token from memory as soon as it is no longer needed.
 *
 * The token is held only in a ref (ephemeral memory) to allow a retry after a transient
 * network/server failure. It is never rendered, logged, put in error copy, or written to
 * localStorage/sessionStorage/IndexedDB/cookies/query. The fragment is never restored.
 *
 * State machine (only states the backend can actually distinguish — verify-email returns
 * 200 on success and 400 `invalid_token` for every invalid/expired/used/already-verified
 * case, so those collapse to a single `invalid_or_expired` state):
 *   missing_token · verifying · verified · invalid_or_expired · network_error
 */

type VerifyState =
  | "missing_token"
  | "verifying"
  | "verified"
  | "invalid_or_expired"
  | "network_error";

/**
 * Extract a token strictly from `#token=<value>`. B1 tokens are URL-safe
 * (`secrets.token_urlsafe` → only `A-Z a-z 0-9 _ -`, no `+ / = %`), so this exact-match
 * regex preserves the token bytes with no decoding, and rejects: no hash, empty token, a
 * different/extra fragment key, malformed characters, or multiple `token=` values.
 */
export function readTokenFromHash(hash: string): string | null {
  const match = /^#token=([A-Za-z0-9_-]+)$/.exec(hash);
  return match ? match[1] : null;
}

export function VerifyEmailClient() {
  const [state, setState] = useState<VerifyState>("verifying");
  const tokenRef = useRef<string | null>(null);
  const startedRef = useRef(false);

  async function verify(token: string | null) {
    if (token === null) {
      setState("missing_token");
      return;
    }
    setState("verifying");
    try {
      await portalApi.verifyEmail(token);
      tokenRef.current = null; // success — the token is spent; drop it
      setState("verified");
    } catch (caught) {
      if (caught instanceof ApiError && caught.kind === "client") {
        // 400 invalid_token — invalid/expired/used; the token cannot be reused. Drop it.
        tokenRef.current = null;
        setState("invalid_or_expired");
      } else {
        // Transient network/server failure — keep the token in memory to allow a retry.
        setState("network_error");
      }
    }
  }

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    const token = readTokenFromHash(window.location.hash);
    if (token !== null) {
      // Strip the fragment from the visible URL/history BEFORE any network call.
      window.history.replaceState(
        null,
        "",
        window.location.pathname + window.location.search,
      );
      tokenRef.current = token;
    }
    // All state transitions happen inside `verify` (a stable helper), not in this effect.
    void verify(token);
  }, []);

  return (
    <div className="sbj-auth__body" aria-live="polite">
      {state === "verifying" ? (
        <>
          <h1 className="sbj-auth__title">Verifying your email</h1>
          <p className="sbj-auth__lede">
            Please wait while we confirm your email address.
          </p>
          <LoadingState label="Verifying…" />
        </>
      ) : null}

      {state === "verified" ? (
        <>
          <h1 className="sbj-auth__title">Your email is verified</h1>
          <p className="sbj-auth__lede">
            Your Sky Bridge Jet account is ready for sign in.
          </p>
          <div className="sbj-auth__actions">
            <Link className="button button--primary" href="/login?verified=1">
              Continue to sign in
            </Link>
          </div>
        </>
      ) : null}

      {state === "invalid_or_expired" ? (
        <>
          <h1 className="sbj-auth__title">
            This verification link can&apos;t be used
          </h1>
          <p className="sbj-auth__lede">
            This link is invalid or has expired. Request a new verification
            email and try again.
          </p>
          <ResendVerificationForm />
          <p className="sbj-auth__alt">
            <Link className="sbj-auth__link" href="/login">
              Back to sign in
            </Link>
          </p>
        </>
      ) : null}

      {state === "missing_token" ? (
        <>
          <h1 className="sbj-auth__title">Verification link unavailable</h1>
          <p className="sbj-auth__lede">
            This verification link is missing or invalid. Request a new
            verification email below.
          </p>
          <ResendVerificationForm />
          <p className="sbj-auth__alt">
            <Link className="sbj-auth__link" href="/login">
              Back to sign in
            </Link>
          </p>
        </>
      ) : null}

      {state === "network_error" ? (
        <>
          <h1 className="sbj-auth__title">
            We couldn&apos;t verify your email
          </h1>
          <Alert tone="error">
            <span>Please try again.</span>
          </Alert>
          <div className="sbj-auth__actions">
            <Button
              type="button"
              onClick={() => {
                if (tokenRef.current !== null) void verify(tokenRef.current);
              }}
            >
              Retry verification
            </Button>
            <Link className="sbj-auth__link" href="/login">
              Back to sign in
            </Link>
          </div>
        </>
      ) : null}
    </div>
  );
}
