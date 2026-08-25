"use client";

import Link from "next/link";

import { useSession } from "@/components/session/session-context";
import { Badge, Card, PageHeading } from "@/components/ui/primitives";

/**
 * The portal dashboard/home. A real, session-aware landing that greets the signed-in user
 * and links to the shell's sections. It shows no fabricated booking/offer/payment data —
 * those surfaces are honest placeholders until their feature phases.
 */
export default function PortalDashboardPage() {
  const { session } = useSession();
  const greetingName =
    session.status === "authenticated"
      ? (session.user.display_name ?? session.user.email)
      : "";

  return (
    <>
      <PageHeading
        title={greetingName ? `Welcome, ${greetingName}` : "Welcome"}
        description="Your Sky Bridge Jet customer portal."
      />
      <div className="card-grid">
        <Card>
          <h2 className="card__title">Trip requests</h2>
          <p>View your private-flight requests and their status.</p>
          <Link className="card__link" href="/portal/trip-requests">
            Go to trip requests
          </Link>
        </Card>
        <Card>
          <h2 className="card__title">Bookings</h2>
          <p>Review your bookings and their status.</p>
          <Link className="card__link" href="/portal/bookings">
            Go to bookings
          </Link>
        </Card>
        <Card>
          <h2 className="card__title">
            Offers <Badge tone="info">Coming soon</Badge>
          </h2>
          <p>Compare operator offers for your trips in an upcoming phase.</p>
          <Link className="card__link" href="/portal/offers">
            Go to offers
          </Link>
        </Card>
        <Card>
          <h2 className="card__title">Account</h2>
          <p>Your sign-in details and customer account.</p>
          <Link className="card__link" href="/portal/account">
            Go to account
          </Link>
        </Card>
      </div>
    </>
  );
}
