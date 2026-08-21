import { RouteDisplay } from "@/components/demo/RouteDisplay";
import { StatusMark } from "@/components/demo/StatusMark";
import { demoFixtures } from "@/lib/demo/fixtures";

export default function DemoBookingsPage() {
  return (
    <>
      <header className="sbj-page-head">
        <p className="sbj-kicker">Bookings</p>
        <h1>Bookings</h1>
        <p>Synthetic status cards for presentation only.</p>
      </header>
      <ol className="sbj-list">
        {demoFixtures.bookings.map((booking) => (
          <li key={booking.id}>
            <article className="sbj-panel">
              <p className="sbj-id">{booking.id}</p>
              <RouteDisplay
                origin={booking.origin}
                destination={booking.destination}
              />
              <p className="sbj-meta">
                <span>{booking.departure}</span>
                <span>{booking.passengers} passengers</span>
                <span>{booking.aircraftCategory}</span>
                <span>{booking.organization}</span>
                <span>{booking.tripId}</span>
              </p>
              <div className="sbj-meta">
                <StatusMark status={booking.status} tone={booking.tone} />
                <span className="sbj-readonly">Read-only</span>
              </div>
            </article>
          </li>
        ))}
      </ol>
    </>
  );
}
