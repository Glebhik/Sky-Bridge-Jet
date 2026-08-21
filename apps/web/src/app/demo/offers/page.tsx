import { Button, Card, PageHeading } from "@/components/ui/primitives";
import { demoFixtures } from "@/lib/demo/fixtures";

export default function DemoOffersPage() {
  return (
    <>
      <PageHeading
        title="Offers"
        description="A synthetic, read-only comparison with no commercial action."
      />
      <div className="card-grid">
        {demoFixtures.offers.map((offer) => (
          <Card as="article" key={offer.id}>
            <p className="demo-portal__reference">{offer.id}</p>
            <h2 className="card__title">{offer.label}</h2>
            <dl className="detail-list">
              <div>
                <dt>Trip</dt>
                <dd>{offer.tripId}</dd>
              </div>
              <div>
                <dt>Category</dt>
                <dd>{offer.category}</dd>
              </div>
              <div>
                <dt>Departure window</dt>
                <dd>{offer.departureWindow}</dd>
              </div>
              <div>
                <dt>Seats</dt>
                <dd>{offer.seats}</dd>
              </div>
              <div>
                <dt>Baggage</dt>
                <dd>{offer.baggage}</dd>
              </div>
              <div>
                <dt>Estimated duration</dt>
                <dd>{offer.estimatedDuration}</dd>
              </div>
            </dl>
            <Button className="demo-portal__disabled-action" disabled>
              Demo only — selection unavailable
            </Button>
          </Card>
        ))}
      </div>
    </>
  );
}
