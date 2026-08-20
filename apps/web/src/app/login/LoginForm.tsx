"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { portalApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { Alert, Button, Field } from "@/components/ui/primitives";

/**
 * The client login form. On success it navigates to the safe return path and refreshes so
 * the protected layout re-validates the (now established) backend session. Credentials are
 * posted through the same-origin proxy; nothing is stored client-side. Errors are surfaced
 * distinctly (invalid credentials vs rate-limited vs transient) without leaking specifics.
 */
export function LoginForm({ returnPath }: { returnPath: string }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await portalApi.login(email, password);
      router.push(returnPath);
      router.refresh();
    } catch (caught) {
      if (caught instanceof ApiError && caught.kind === "rate_limited") {
        setError("Too many attempts. Please wait a moment and try again.");
      } else if (
        caught instanceof ApiError &&
        (caught.status === 401 || caught.kind === "client")
      ) {
        setError("Invalid email or password.");
      } else {
        setError("We couldn’t sign you in right now. Please try again.");
      }
      setSubmitting(false);
    }
  }

  return (
    <form className="auth-form" onSubmit={handleSubmit} noValidate>
      {error ? (
        <Alert tone="error">
          <span>{error}</span>
        </Alert>
      ) : null}
      <Field
        label="Email"
        id="login-email"
        type="email"
        name="email"
        autoComplete="email"
        required
        value={email}
        onChange={(event) => setEmail(event.target.value)}
      />
      <Field
        label="Password"
        id="login-password"
        type="password"
        name="password"
        autoComplete="current-password"
        required
        value={password}
        onChange={(event) => setPassword(event.target.value)}
      />
      <Button type="submit" disabled={submitting}>
        {submitting ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}
