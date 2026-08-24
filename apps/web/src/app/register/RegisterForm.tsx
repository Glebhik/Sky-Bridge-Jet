"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { portalApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { Alert, Button, Field } from "@/components/ui/primitives";

/**
 * The real customer registration form (Phase 9.2.B2.1).
 *
 * Collects only email + password (+ a UI-only confirm). On success it never auto-logs-in and
 * never reads the response `verification_token` (a dev-only field that is null in production);
 * it swaps to a "check your email" panel and offers an enumeration-safe resend. Nothing is
 * persisted to localStorage/sessionStorage/cookies; the backend remains authoritative.
 */

const PASSWORD_HINT =
  "At least 12 characters, including upper- and lower-case letters.";
const MIN_PASSWORD = 12;
const MAX_PASSWORD = 200;
const RESEND_ACK =
  "If the account requires verification, we've sent new instructions.";

/** Mirror the backend rule (length 12–200, at least one upper- and one lower-case letter). */
function passwordMeetsRule(password: string): boolean {
  return (
    password.length >= MIN_PASSWORD &&
    password.length <= MAX_PASSWORD &&
    password.toLowerCase() !== password &&
    password.toUpperCase() !== password
  );
}

type ResendState = "idle" | "sending" | "done" | "wait" | "error";

export function RegisterForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [registeredEmail, setRegisteredEmail] = useState<string | null>(null);
  const [resend, setResend] = useState<ResendState>("idle");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    // Client-side convenience validation only; the backend is authoritative.
    if (!passwordMeetsRule(password)) {
      setError("Check your email and password and try again.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    const submittedEmail = email.trim();
    setSubmitting(true);
    try {
      // Only { email, password } is sent. The response is intentionally ignored — the UI
      // must behave as though `verification_token` does not exist (real email is canonical).
      await portalApi.register(submittedEmail, password);
      setRegisteredEmail(submittedEmail);
    } catch (caught) {
      if (caught instanceof ApiError && caught.kind === "conflict") {
        setError(
          "An account with this email may already exist. Try signing in.",
        );
      } else if (caught instanceof ApiError && caught.kind === "rate_limited") {
        setError("Too many registration attempts. Please wait and try again.");
      } else if (caught instanceof ApiError && caught.kind === "client") {
        setError("Check your email and password and try again.");
      } else {
        setError(
          "We couldn't create your account right now. Please try again.",
        );
      }
      setSubmitting(false);
    }
  }

  async function handleResend() {
    if (registeredEmail === null || resend === "sending") return;
    setResend("sending");
    try {
      await portalApi.resendVerification(registeredEmail);
      setResend("done");
    } catch (caught) {
      // Never reveal account existence/eligibility. A 429 (rate limit) or transient failure
      // is independent of whether the account exists, so we surface a neutral message.
      setResend(
        caught instanceof ApiError && caught.kind === "rate_limited"
          ? "wait"
          : "error",
      );
    }
  }

  if (registeredEmail !== null) {
    return (
      <div className="sbj-auth__body">
        <header className="sbj-auth__heading">
          <span
            className="sbj-auth__status-mark sbj-auth__status-mark--positive"
            aria-hidden="true"
          />
          <h1 className="sbj-auth__title">Check your email</h1>
        </header>
        <p className="sbj-auth__lede">
          If everything is in order, we&apos;ve sent a verification link to{" "}
          <strong className="sbj-auth__email">{registeredEmail}</strong>
        </p>
        <p className="sbj-auth__muted">The link expires in 24 hours.</p>
        <p className="sbj-auth__muted">
          Please check your inbox and spam folder.
        </p>
        {resend === "done" || resend === "wait" || resend === "error" ? (
          <Alert tone={resend === "error" ? "error" : "info"}>
            <span>
              {resend === "wait"
                ? "Please wait a moment before requesting another email."
                : resend === "error"
                  ? "We couldn't send instructions right now. Please try again."
                  : RESEND_ACK}
            </span>
          </Alert>
        ) : null}
        <div className="sbj-auth__actions">
          <Button
            type="button"
            variant="secondary"
            onClick={handleResend}
            disabled={resend === "sending"}
          >
            {resend === "sending" ? "Sending…" : "Resend verification email"}
          </Button>
          <Link className="sbj-auth__link" href="/login">
            Back to sign in
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="sbj-auth__body">
      <header className="sbj-auth__heading">
        <h1 className="sbj-auth__title">Create your account</h1>
      </header>
      <p className="sbj-auth__lede">
        Set up secure access to your Sky Bridge Jet customer portal.
      </p>
      <form className="sbj-auth__form" onSubmit={handleSubmit} noValidate>
        {error ? (
          <Alert tone="error">
            <span>{error}</span>
          </Alert>
        ) : null}
        <Field
          label="Email"
          id="register-email"
          type="email"
          name="email"
          autoComplete="email"
          inputMode="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <div className="sbj-auth__field-group">
          <Field
            label="Password"
            id="register-password"
            type="password"
            name="password"
            autoComplete="new-password"
            required
            aria-describedby="register-password-hint"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <p id="register-password-hint" className="sbj-auth__hint">
            {PASSWORD_HINT}
          </p>
        </div>
        <Field
          label="Confirm password"
          id="register-confirm-password"
          type="password"
          name="confirm-password"
          autoComplete="new-password"
          required
          value={confirmPassword}
          onChange={(event) => setConfirmPassword(event.target.value)}
        />
        <Button type="submit" disabled={submitting}>
          {submitting ? "Creating account…" : "Create account"}
        </Button>
      </form>
      <p className="sbj-auth__alt">
        Already have an account?{" "}
        <Link className="sbj-auth__link" href="/login">
          Sign in
        </Link>
      </p>
    </div>
  );
}
