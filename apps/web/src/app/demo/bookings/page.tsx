import { Badge, Card, PageHeading } from "@/components/ui/primitives";
import { demoFixtures } from "@/lib/demo/fixtures";

export default function DemoBookingsPage() {
  return (
    <>
      <PageHeading
        title="Bookings"
        description="Synthetic status cards for presentation only."
      />
      <ul className="resource-list">
        {demoFixtures.bookings.map((booking) => (
          <li key={booking.id}>
            <Card as="article">
              <div className="resource-list__row">
                <div>
                  <p className="demo-portal__reference">{booking.id}</p>
                  <p>{booking.route}</p>
                  <p className="demo-portal__meta">{booking.departure}</p>
                  <p className="demo-portal__meta">{booking.tripId}</p>
                </div>
                <Badge tone={booking.tone}>{booking.status}</Badge>
              </div>
            </Card>
          </li>
        ))}
      </ul>
    </>
  );
}
