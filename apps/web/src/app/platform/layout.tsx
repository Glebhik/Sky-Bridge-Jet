import { headers } from "next/headers";
import Link from "next/link";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { Alert, Container } from "@/components/ui/primitives";
import { getServerSession } from "@/lib/session/server";

export default async function PlatformLayout({
  children,
}: {
  children: ReactNode;
}) {
  const session = await getServerSession();
  if (session.status === "unauthenticated") {
    const pathname =
      (await headers()).get("x-portal-pathname") ?? "/platform/compliance";
    redirect(`/staff-sign-in?next=${encodeURIComponent(pathname)}`);
  }
  if (session.status !== "authenticated") {
    return (
      <Container>
        <Alert tone="error" title="We couldn’t load your account">
          Refresh to try again.
        </Alert>
      </Container>
    );
  }
  const platformMember = session.memberships.some(
    (item) => item.organization_type === "PLATFORM",
  );
  if (!session.privilegedMfaAssured) {
    return (
      <Container>
        <Alert tone="error" title="Staff authentication required">
          Re-authenticate with MFA to access the platform workspace.{" "}
          <Link href="/api/proxy/auth/platform/login">Staff sign in</Link>
        </Alert>
      </Container>
    );
  }
  const canReview = session.permissions.includes("compliance.review");
  const canReadPayments = session.permissions.includes("payment.read");
  const canReadPilot = session.permissions.includes("pilot.read");
  if (!platformMember || (!canReview && !canReadPayments && !canReadPilot)) {
    return (
      <Container>
        <Alert tone="error" title="Platform workspace access required">
          This internal workspace is limited to authorized platform staff.
        </Alert>
      </Container>
    );
  }
  return (
    <main id="platform-main" className="platform platform-main">
      {process.env.APP_ENVIRONMENT === "staging" ? (
        <Alert tone="warning" title="STAGING — CONTROLLED PILOT">
          NO REAL MONEY
        </Alert>
      ) : null}
      <nav className="platform-nav" aria-label="Platform workspace">
        {canReview ? <Link href="/platform/compliance">Compliance</Link> : null}
        {canReadPayments ? (
          <Link href="/platform/payments">Payments</Link>
        ) : null}
        {canReadPilot ? (
          <Link href="/platform/pilot">Pilot governance</Link>
        ) : null}
      </nav>
      {children}
    </main>
  );
}
