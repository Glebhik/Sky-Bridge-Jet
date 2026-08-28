import { headers } from "next/headers";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";
import Link from "next/link";

import { Alert, Container } from "@/components/ui/primitives";
import { buildLoginRedirect } from "@/lib/auth/redirect";
import { getServerSession } from "@/lib/session/server";

export default async function OperatorLayout({
  children,
}: {
  children: ReactNode;
}) {
  const session = await getServerSession();
  if (session.status === "unauthenticated") {
    const pathname =
      (await headers()).get("x-portal-pathname") ?? "/operator/bookings";
    redirect(buildLoginRedirect(pathname));
  }
  if (session.status === "error" || session.status === "loading") {
    return (
      <div className="operator">
        <Container>
          <Alert tone="error" title="We couldn’t load your account">
            Please refresh to try again.
          </Alert>
        </Container>
      </div>
    );
  }
  const operatorOrganizations = session.memberships.filter(
    (membership) => membership.organization_type === "OPERATOR",
  );
  if (operatorOrganizations.length === 0) {
    return (
      <div className="operator">
        <Container>
          <Alert tone="error" title="Operator access required">
            This area is available only to members of an operator organization.
          </Alert>
        </Container>
      </div>
    );
  }
  return (
    <main id="operator-main" className="operator operator-main">
      <div className="operator__atmosphere" aria-hidden="true">
        <div className="operator__grid" />
        <div className="operator__glow" />
      </div>
      <nav className="operator-nav" aria-label="Operator workspace">
        <Link href="/operator/opportunities">Opportunities</Link>
        <Link href="/operator/bookings">Bookings</Link>
        <Link href="/operator/bookings/history">History</Link>
        <Link href="/operator/compliance">Compliance</Link>
      </nav>
      {children}
    </main>
  );
}
