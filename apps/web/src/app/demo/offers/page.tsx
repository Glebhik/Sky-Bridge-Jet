import { AbstractCraft } from "@/components/demo/Atmosphere";
import {
  DEMO_OFFER_INERT_LABEL,
  DEMO_OFFER_READ_ONLY_LABEL,
} from "@/lib/demo/copy";
import { demoFixtures } from "@/lib/demo/fixtures";

export default function DemoOffersPage() {
  return (
    <>
      <header className="sbj-page-head">
        <p className="sbj-kicker">Offers</p>
        <h1>Offers</h1>
        <p>A synthetic, read-only comparison with no commercial action.</p>
      </header>
      <div className="sbj-grid sbj-grid--2">
        {demoFixtures.offers.map((offer) => (
          <article className="sbj-panel" key={offer.id}>
            <AbstractCraft />
            <p className="sbj-id">{offer.id}</p>
            <h2 className="sbj-stat">{offer.label}</h2>
            <dl className="sbj-dl">
              <div>
                <dt>Trip</dt>
                <dd>{offer.tripId}</dd>
              </div>
              <div>
                <dt>Category</dt>
                <dd>{offer.category}</dd>
              </div>
              <div>
                <dt>Cabin</dt>
                <dd>{offer.model}</dd>
              </div>
              <div>
                <dt>Departure window</dt>
                <dd>{offer.departureWindow}</dd>
              </div>
              <div>
                <dt>Passenger capacity</dt>
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
            <p className="sbj-readonly">{DEMO_OFFER_READ_ONLY_LABEL}</p>
            <p className="sbj-inert">{DEMO_OFFER_INERT_LABEL}</p>
          </article>
        ))}
      </div>
    </>
  );
}
