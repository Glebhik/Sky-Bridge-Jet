"use client";

import { useState } from "react";

import { useActiveOrganization } from "@/components/session/org-context";
import { useSession } from "@/components/session/session-context";
import { portalApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import {
  Alert,
  Badge,
  Button,
  Card,
  PageHeading,
} from "@/components/ui/primitives";

/**
 * Account placeholder. Shows the signed-in identity and customer-account context. When the
 * account has no usable customer organization, it offers a single, *explicit* recovery
 * action (never automatic) that calls the Phase 9.1.A recovery endpoint and then
 * re-validates the session. Profile editing is a later phase.
 */
export default function PortalAccountPage() {
  const { session, refresh } = useSession();
  const { organizations, hasCustomerContext } = useActiveOrganization();
  const [recovering, setRecovering] = useState(false);
  const [message, setMessage] = useState<{
    tone: "success" | "error";
    text: string;
  } | null>(null);

  const user = session.status === "authenticated" ? session.user : null;

  async function handleRecover() {
    setRecovering(true);
    setMessage(null);
    try {
      await portalApi.recoverCustomerAccount();
      await refresh();
      setMessage({ tone: "success", text: "Your personal account is ready." });
    } catch (error) {
      const text =
        error instanceof ApiError && error.kind === "conflict"
          ? "This account already has an organization or a pending invitation to accept."
          : error instanceof ApiError && error.kind === "rate_limited"
            ? "Too many attempts. Please try again shortly."
            : "We couldn’t complete recovery. Please try again.";
      setMessage({ tone: "error", text });
    } finally {
      setRecovering(false);
    }
  }

  return (
    <>
      <PageHeading
        title="Account"
        description="Your sign-in and customer account details."
      />
      <Card>
        <h2 className="card__title">Sign-in</h2>
        {user ? (
          <dl className="detail-list">
            <div>
              <dt>Email</dt>
              <dd>{user.email}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>
                <Badge tone={user.status === "ACTIVE" ? "success" : "warning"}>
                  {user.status}
                </Badge>
              </dd>
            </div>
          </dl>
        ) : null}
      </Card>

      <Card>
        <h2 className="card__title">Customer account</h2>
        {hasCustomerContext ? (
          <p>
            You have {organizations.length} customer{" "}
            {organizations.length === 1 ? "account" : "accounts"} available.
          </p>
        ) : (
          <>
            <p>This sign-in isn’t linked to a customer account yet.</p>
            <Button onClick={handleRecover} disabled={recovering}>
              {recovering ? "Setting up…" : "Recover personal account"}
            </Button>
          </>
        )}
        {message ? (
          <div className="account__message">
            <Alert tone={message.tone === "success" ? "success" : "error"}>
              {message.text}
            </Alert>
          </div>
        ) : null}
      </Card>
    </>
  );
}
