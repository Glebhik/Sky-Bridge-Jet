import type { ReactNode } from "react";

import { Alert, Container } from "@/components/ui/primitives";
import { getServerSession } from "@/lib/session/server";

export default async function ComplianceLayout({
  children,
}: {
  children: ReactNode;
}) {
  const session = await getServerSession();
  if (
    session.status !== "authenticated" ||
    !session.permissions.includes("compliance.review")
  ) {
    return (
      <Container>
        <Alert tone="error" title="Compliance reviewer access required">
          This workspace requires the canonical compliance review permission.
        </Alert>
      </Container>
    );
  }
  return children;
}
