import type { Metadata } from "next";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { DemoPortalShell } from "@/components/demo/DemoPortalShell";
import { isDemoPortalEnabled } from "@/lib/demo/config";

// Evaluate the server-only environment flag at request time rather than baking demo
// availability into a static page during the build.
export const dynamic = "force-dynamic";

// The synthetic demo is never for public search indexing, even when the feature flag is
// enabled. Scoped to the /demo subtree only via this layout, so `/`, `/login`, and the
// authenticated `/portal` are unaffected. Renders `<meta name="robots" content="noindex,
// nofollow">` (and the Googlebot equivalent) on every enabled demo route.
export const metadata: Metadata = {
  robots: {
    index: false,
    follow: false,
    googleBot: {
      index: false,
      follow: false,
    },
  },
};

/** Fail-closed public demo boundary, completely separate from authenticated /portal. */
export default function DemoLayout({ children }: { children: ReactNode }) {
  if (!isDemoPortalEnabled()) {
    notFound();
  }

  return <DemoPortalShell>{children}</DemoPortalShell>;
}
