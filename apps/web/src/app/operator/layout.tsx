import { headers } from "next/headers";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

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
      <Container>
        <Alert tone="error" title="We couldn’t load your account">
          Please refresh to try again.
        </Alert>
      </Container>
    );
  }
  const operatorOrganizations = session.memberships.filter(
    (membership) => membership.organization_type === "OPERATOR",
  );
  if (operatorOrganizations.length === 0) {
    return (
      <Container>
        <Alert tone="error" title="Operator access required">
          This area is available only to members of an operator organization.
        </Alert>
      </Container>
    );
  }
  return (
    <main id="operator-main" className="operator-main">
      {children}
    </main>
  );
}
