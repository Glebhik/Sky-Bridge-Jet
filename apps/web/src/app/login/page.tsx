import { redirect } from "next/navigation";

import { LoginForm } from "@/app/login/LoginForm";
import { sanitizeReturnPath } from "@/lib/auth/redirect";
import { getServerSession } from "@/lib/session/server";

/**
 * The login page. If the visitor already has a live backend session they are sent straight
 * to their safe return path (no need to log in again). Otherwise the client login form is
 * rendered. The `next` return path is sanitized to a same-origin path server-side before it
 * is ever handed to the form.
 */
export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string | string[] }>;
}) {
  const params = await searchParams;
  const rawNext = Array.isArray(params.next) ? params.next[0] : params.next;
  const returnPath = sanitizeReturnPath(rawNext);

  const session = await getServerSession();
  if (session.status === "authenticated") {
    redirect(returnPath);
  }

  return (
    <main className="auth-page">
      <div className="auth-card">
        <h1 className="auth-card__title">Sign in</h1>
        <p className="auth-card__subtitle">
          Access your Sky Bridge Jet customer portal.
        </p>
        <LoginForm returnPath={returnPath} />
      </div>
    </main>
  );
}
