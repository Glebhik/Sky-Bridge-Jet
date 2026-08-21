import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { DemoPortalShell } from "@/components/demo/DemoPortalShell";
import { isDemoPortalEnabled } from "@/lib/demo/config";

// Evaluate the server-only environment flag at request time rather than baking demo
// availability into a static page during the build.
export const dynamic = "force-dynamic";

/** Fail-closed public demo boundary, completely separate from authenticated /portal. */
export default function DemoLayout({ children }: { children: ReactNode }) {
  if (!isDemoPortalEnabled()) {
    notFound();
  }

  return <DemoPortalShell>{children}</DemoPortalShell>;
}
