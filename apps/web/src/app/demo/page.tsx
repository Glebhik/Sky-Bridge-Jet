import Link from "next/link";

import { RouteDisplay } from "@/components/demo/RouteDisplay";
import { StatusMark } from "@/components/demo/StatusMark";
import { demoFixtures } from "@/lib/demo/fixtures";

export default function DemoDashboardPage() {
  const trip = demoFixtures.upcomingTrip;
  const awaiting = demoFixtures.bookings.filter(
    (booking) => booking.status === "Awaiting confirmation",
  ).length;
  const confirmed = demoFixtures.bookings.filter(
    (booking) => booking.status === "Confirmed",
  ).length;

  return (
    <>
      <header className="sbj-page-head">
        <p className="sbj-kicker">Dashboard</p>
        <h1>Welcome, {demoFixtures.customer.name}</h1>
        <p>A read-only view of the Customer Portal Demonstration.</p>
      </header>

      <article className="sbj-panel sbj-panel--featured">
        <p className="sbj-kicker">Upcoming journey</p>
        <p className="sbj-id">{trip.id}</p>
        <RouteDisplay origin={trip.origin} destination={trip.destination} />
        <p className="sbj-meta">
          <span>{trip.departure}</span>
          <span>{trip.passengers} passengers</span>
          <span>{trip.aircraftCategory}</span>
          <span>{trip.organization}</span>
        </p>
        <div className="sbj-meta">
          <StatusMark status={trip.status} tone="warning" />
          <span className="sbj-readonly">Read-only</span>
        </div>
        <Link className="sbj-link" href="/demo/bookings">
          View bookings
        </Link>
      </article>

      <div className="sbj-stack">
        <div className="sbj-grid sbj-grid--2">
          <section className="sbj-panel">
            <p className="sbj-kicker">Bookings</p>
            <h2 className="sbj-stat">{awaiting} awaiting confirmation</h2>
            <p className="sbj-activity__detail">{confirmed} confirmed</p>
            <Link className="sbj-link" href="/demo/bookings">
              View bookings
            </Link>
          </section>
          <section className="sbj-panel">
            <p className="sbj-kicker">Offers</p>
            <h2 className="sbj-stat">
              {demoFixtures.offers.length} synthetic comparison options
            </h2>
            <p className="sbj-activity__detail">
              No offer can be selected in this demonstration.
            </p>
            <Link className="sbj-link" href="/demo/offers">
              View offers
            </Link>
          </section>
        </div>

        <section className="sbj-panel">
          <p className="sbj-kicker">Recent activity</p>
          <ul className="sbj-list">
            {demoFixtures.activity.map((item) => (
              <li key={item.id}>
                <p className="sbj-activity__title">{item.title}</p>
                <p className="sbj-activity__detail">{item.detail}</p>
              </li>
            ))}
          </ul>
          <Link className="sbj-link" href="/demo/account">
            View account
          </Link>
        </section>
      </div>
    </>
  );
}
