import type { ReactNode } from "react";

import { Alert, Container } from "@/components/ui/primitives";
import { getServerSession } from "@/lib/session/server";

export default async function PaymentsLayout({
  children,
}: {
  children: ReactNode;
}) {
  const session = await getServerSession();
  if (
    session.status !== "authenticated" ||
    !session.permissions.includes("payment.read")
  ) {
    return (
      <Container>
        <Alert tone="error" title="Payment review access required">
          This workspace requires the canonical payment read permission.
        </Alert>
      </Container>
    );
  }
  return children;
}
