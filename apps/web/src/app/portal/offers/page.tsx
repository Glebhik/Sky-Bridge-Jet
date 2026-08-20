"use client";

import { EmptyState, PageHeading } from "@/components/ui/primitives";

/**
 * Offers placeholder. Operator offers are surfaced per trip request; the customer-facing
 * offer-comparison workflow is a later phase, so this page is an honest empty state rather
 * than fabricated offer or pricing data.
 */
export default function PortalOffersPage() {
  return (
    <>
      <PageHeading
        title="Offers"
        description="Operator offers for your trip requests."
      />
      <EmptyState
        title="Offer comparison is coming soon"
        description="You’ll compare operator offers for your trips here in an upcoming phase."
      />
    </>
  );
}
