import Link from "next/link";

import { Badge, Card, PageHeading } from "@/components/ui/primitives";
import { demoFixtures } from "@/lib/demo/fixtures";

export default function DemoDashboardPage() {
  const awaiting = demoFixtures.bookings.filter(
    (booking) => booking.status === "Awaiting confirmation",
  ).length;
  const confirmed = demoFixtures.bookings.filter(
    (booking) => booking.status === "Confirmed",
  ).length;

  return (
    <>
      <PageHeading
        title={`Welcome, ${demoFixtures.customer.name}`}
        description="A read-only view of the Customer Portal Demonstration."
      />
      <Card>
        <h2 className="card__title">Active demonstration organization</h2>
        <p>{demoFixtures.customer.organization}</p>
        <Badge tone="info">{demoFixtures.customer.accessLabel}</Badge>
      </Card>
      <div className="card-grid demo-portal__dashboard-grid">
        <Card>
          <h2 className="card__title">Upcoming trip</h2>
          <p className="demo-portal__reference">
            {demoFixtures.upcomingTrip.id}
          </p>
          <p>{demoFixtures.upcomingTrip.route}</p>
          <p>{demoFixtures.upcomingTrip.departure}</p>
          <p>{demoFixtures.upcomingTrip.passengers} passengers</p>
          <Link className="card__link" href="/demo/bookings">
            View demonstration bookings
          </Link>
        </Card>
        <Card>
          <h2 className="card__title">Booking status</h2>
          <p>{awaiting} awaiting confirmation</p>
          <p>{confirmed} confirmed</p>
          <Link className="card__link" href="/demo/bookings">
            Review status presentation
          </Link>
        </Card>
        <Card>
          <h2 className="card__title">Available offers</h2>
          <p>{demoFixtures.offers.length} synthetic comparison options</p>
          <p>No offer can be selected in this demonstration.</p>
          <Link className="card__link" href="/demo/offers">
            Compare demonstration offers
          </Link>
        </Card>
      </div>
    </>
  );
}
