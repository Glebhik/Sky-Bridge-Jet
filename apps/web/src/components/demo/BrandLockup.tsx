import Link from "next/link";

import { DEMO_BRAND_NAME, DEMO_BRAND_SUBLINE } from "@/lib/demo/copy";

/**
 * Text lockup for the demonstration. The brand-mark slot is reserved for the approved
 * champagne-gold wing emblem; no substitute symbol is rendered.
 */
export function BrandLockup({ compact = false }: { compact?: boolean }) {
  return (
    <Link href="/demo" className="sbj-brand">
      <span className="sbj-brand__mark-slot" aria-hidden="true" />
      <span className="sbj-brand__text">
        <span className="sbj-brand__name">{DEMO_BRAND_NAME}</span>
        {compact ? null : (
          <span className="sbj-brand__subline">{DEMO_BRAND_SUBLINE}</span>
        )}
      </span>
    </Link>
  );
}
