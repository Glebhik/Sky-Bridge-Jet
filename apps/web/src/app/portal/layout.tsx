import { headers } from "next/headers";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { OrganizationProvider } from "@/components/session/org-context";
import { SessionProvider } from "@/components/session/session-context";
import { PortalShell } from "@/components/shell/PortalShell";
import { Alert, Container } from "@/components/ui/primitives";
import { buildLoginRedirect } from "@/lib/auth/redirect";
import { getServerSession } from "@/lib/session/server";

/**
 * The protected portal boundary. It validates the backend session on the server *before*
 * rendering any protected content, so unauthenticated users are redirected to login (with
 * a safe return path) without ever flashing customer data. A transient backend failure
 * shows a recoverable error rather than logging the user out. Authenticated requests are
 * wrapped in the session and active-organization providers and the responsive shell.
 */
export default async function PortalLayout({
  children,
}: {
  children: ReactNode;
}) {
  const session = await getServerSession();

  if (session.status === "unauthenticated") {
    const pathname = (await headers()).get("x-portal-pathname") ?? "/portal";
    redirect(buildLoginRedirect(pathname));
  }

  if (session.status === "error") {
    return (
      <main className="portal-main" id="portal-main">
        <Container>
          <Alert tone="error" title="We couldn’t load your account">
            The service is temporarily unavailable. Please refresh to try again
            — you have not been signed out.
          </Alert>
        </Container>
      </main>
    );
  }

  return (
    <SessionProvider initialSession={session}>
      <OrganizationProvider>
        <PortalShell>{children}</PortalShell>
      </OrganizationProvider>
    </SessionProvider>
  );
}
