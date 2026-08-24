import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { RegisterForm } from "@/app/register/RegisterForm";
import { AuthShell } from "@/components/auth/AuthShell";
import { getServerSession } from "@/lib/session/server";

/**
 * The real customer registration page. An already-authenticated visitor is sent to the
 * portal rather than being shown the form. `noindex, nofollow` for this local-first phase.
 * The description is factual account-access copy (never the old marketing phrase), and the
 * route-specific metadata supersedes the inherited root description on this page.
 */
export const metadata: Metadata = {
  title: "Sky Bridge Jet — Create Account",
  description: "Create secure access to your Sky Bridge Jet customer portal.",
  robots: {
    index: false,
    follow: false,
    googleBot: { index: false, follow: false },
  },
};

export default async function RegisterPage() {
  const session = await getServerSession();
  if (session.status === "authenticated") {
    redirect("/portal");
  }
  return (
    <AuthShell>
      <RegisterForm />
    </AuthShell>
  );
}
