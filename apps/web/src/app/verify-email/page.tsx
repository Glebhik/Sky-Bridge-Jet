import type { Metadata } from "next";

import { VerifyEmailClient } from "@/app/verify-email/VerifyEmailClient";
import { AuthShell } from "@/components/auth/AuthShell";

/**
 * Email-verification page (Phase 9.2.B2.2). A thin server shell that renders the client
 * verifier inside the production auth shell. The server never needs — and never receives —
 * the raw verification token: it travels only in the URL fragment, which is not sent in the
 * HTTP request, and there is no `searchParams`/query token here. `noindex, nofollow` because
 * this is a token-consumption surface.
 */
export const metadata: Metadata = {
  title: "Sky Bridge Jet — Verify Email",
  description: "Confirm your Sky Bridge Jet email address.",
  robots: {
    index: false,
    follow: false,
    googleBot: { index: false, follow: false },
  },
};

export default function VerifyEmailPage() {
  return (
    <AuthShell>
      <VerifyEmailClient />
    </AuthShell>
  );
}
