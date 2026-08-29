import type { Metadata } from "next";
import Link from "next/link";

import { AuthShell } from "@/components/auth/AuthShell";

export const metadata: Metadata = {
  title: "Sky Bridge Jet — Staff Sign In",
  robots: { index: false, follow: false },
};

export default function StaffSignInPage() {
  return (
    <AuthShell>
      <div className="sbj-auth__body">
        <header className="sbj-auth__heading">
          <h1 className="sbj-auth__title">Staff sign in</h1>
        </header>
        <p className="sbj-auth__lede">
          Platform access requires your managed staff identity and MFA.
        </p>
        <Link className="button" href="/api/proxy/auth/platform/login">
          Continue with staff authentication
        </Link>
        <p className="sbj-auth__alt">
          Customer or operator? <Link href="/login">Use regular sign in</Link>
        </p>
      </div>
    </AuthShell>
  );
}
