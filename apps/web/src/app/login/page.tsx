import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { LoginForm } from "@/app/login/LoginForm";
import { AuthShell } from "@/components/auth/AuthShell";
import { Alert } from "@/components/ui/primitives";
import { sanitizeReturnPath } from "@/lib/auth/redirect";
import { getServerSession } from "@/lib/session/server";

/**
 * The login page. If the visitor already has a live backend session they are sent straight
 * to their safe return path (no need to log in again). Otherwise the client login form is
 * rendered inside the production auth shell. The `next` return path is sanitized to a
 * same-origin path server-side before it is ever handed to the form. `noindex, nofollow`
 * for this local-first phase. Session/CSRF/redirect behaviour is unchanged.
 */
export const metadata: Metadata = {
  title: "Sky Bridge Jet — Sign In",
  description: "Sign in to your Sky Bridge Jet customer portal.",
  robots: {
    index: false,
    follow: false,
    googleBot: { index: false, follow: false },
  },
};

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{
    next?: string | string[];
    verified?: string | string[];
  }>;
}) {
  const params = await searchParams;
  const rawNext = Array.isArray(params.next) ? params.next[0] : params.next;
  const returnPath = sanitizeReturnPath(rawNext);
  // Strictly a fixed flag: only the exact value "1" shows the banner. No query content is
  // ever reflected into the page, so `verified=<anything else>` renders nothing.
  const rawVerified = Array.isArray(params.verified)
    ? params.verified[0]
    : params.verified;
  const showVerifiedBanner = rawVerified === "1";

  const session = await getServerSession();
  if (session.status === "authenticated") {
    redirect(returnPath);
  }

  return (
    <AuthShell>
      <div className="sbj-auth__body">
        <header className="sbj-auth__heading">
          <h1 className="sbj-auth__title">Sign in</h1>
        </header>
        <p className="sbj-auth__lede">
          Access your Sky Bridge Jet customer portal.
        </p>
        {showVerifiedBanner ? (
          <div className="sbj-auth__verified">
            <Alert tone="success">
              <span>Your email is verified. Sign in to continue.</span>
            </Alert>
          </div>
        ) : null}
        <LoginForm returnPath={returnPath} />
        <p className="sbj-auth__alt">
          New to Sky Bridge Jet?{" "}
          <Link className="sbj-auth__link" href="/register">
            Create an account
          </Link>
        </p>
      </div>
    </AuthShell>
  );
}
