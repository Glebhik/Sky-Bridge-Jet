import { headers } from "next/headers";
import Link from "next/link";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { Alert, Container } from "@/components/ui/primitives";
import { buildLoginRedirect } from "@/lib/auth/redirect";
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
    redirect(buildLoginRedirect(pathname));
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
  const canReview = session.permissions.includes("compliance.review");
  const canReadPayments = session.permissions.includes("payment.read");
  if (!platformMember || (!canReview && !canReadPayments)) {
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
      <nav className="platform-nav" aria-label="Platform workspace">
        {canReview ? <Link href="/platform/compliance">Compliance</Link> : null}
        {canReadPayments ? (
          <Link href="/platform/payments">Payments</Link>
        ) : null}
      </nav>
      {children}
    </main>
  );
}
