"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/primitives";
import { useSession } from "@/components/session/session-context";
import { LOGIN_PATH } from "@/lib/auth/redirect";

/**
 * The signed-in user's identity and session actions. Sign-out ends the backend session
 * (best-effort) and then routes to login; the session context reflects unauthenticated
 * regardless, so the UI never continues to treat the user as signed in.
 */
export function UserMenu() {
  const { session, logout } = useSession();
  const router = useRouter();
  const [signingOut, setSigningOut] = useState(false);

  const label =
    session.status === "authenticated"
      ? (session.user.display_name ?? session.user.email)
      : "Account";

  async function handleSignOut() {
    setSigningOut(true);
    await logout();
    router.push(LOGIN_PATH);
  }

  return (
    <div className="user-menu">
      <span className="user-menu__identity" title={label}>
        {label}
      </span>
      <Button
        variant="ghost"
        onClick={handleSignOut}
        disabled={signingOut}
        aria-label="Sign out"
      >
        {signingOut ? "Signing out…" : "Sign out"}
      </Button>
    </div>
  );
}
