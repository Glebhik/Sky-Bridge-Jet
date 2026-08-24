"use client";

import { useState, type FormEvent } from "react";

import { portalApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { Alert, Button, Field } from "@/components/ui/primitives";

/**
 * A small, reusable "request a new verification email" form (Phase 9.2.B2.2).
 *
 * The verification token never safely exposes the account email client-side, so the user
 * enters their email explicitly. The acknowledgement is uniform and enumeration-safe: it
 * never reveals whether the account exists, its status, the provider outcome, or a token.
 * A 429 and transient failures surface neutral messages independent of account existence,
 * and the copy never branches on network timing (so the B1 resend timing side-channel is
 * not surfaced by the UI). Nothing is persisted client-side.
 */

const RESEND_ACK =
  "If the account requires verification, we've sent new instructions.";

type ResendState = "idle" | "sending" | "done" | "wait" | "error";

export function ResendVerificationForm() {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<ResendState>("idle");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (state === "sending") return;
    setState("sending");
    try {
      await portalApi.resendVerification(email.trim());
      setState("done");
    } catch (caught) {
      setState(
        caught instanceof ApiError && caught.kind === "rate_limited"
          ? "wait"
          : "error",
      );
    }
  }

  return (
    <form className="sbj-auth__form" onSubmit={handleSubmit} noValidate>
      {state === "done" || state === "wait" || state === "error" ? (
        <Alert tone={state === "error" ? "error" : "info"}>
          <span>
            {state === "wait"
              ? "Please wait a moment before requesting another email."
              : state === "error"
                ? "We couldn't send instructions right now. Please try again."
                : RESEND_ACK}
          </span>
        </Alert>
      ) : null}
      <Field
        label="Email"
        id="resend-email"
        type="email"
        name="email"
        autoComplete="email"
        inputMode="email"
        required
        value={email}
        onChange={(event) => setEmail(event.target.value)}
      />
      <Button type="submit" variant="secondary" disabled={state === "sending"}>
        {state === "sending" ? "Sending…" : "Send a new verification email"}
      </Button>
    </form>
  );
}
