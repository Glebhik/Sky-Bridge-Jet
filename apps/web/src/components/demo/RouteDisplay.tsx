import { RouteArc } from "@/components/demo/Atmosphere";
import type { DemoLocation } from "@/lib/demo/fixtures";

export function RouteDisplay({
  origin,
  destination,
}: {
  origin: DemoLocation;
  destination: DemoLocation;
}) {
  return (
    <p
      className="sbj-route"
      aria-label={`${origin.city} ${origin.iata} to ${destination.city} ${destination.iata}`}
    >
      <span className="sbj-route__end">
        <span className="sbj-route__iata">{origin.iata}</span>
        <span className="sbj-route__city">{origin.city}</span>
      </span>
      <RouteArc />
      <span className="sbj-route__end sbj-route__end--to">
        <span className="sbj-route__iata">{destination.iata}</span>
        <span className="sbj-route__city">{destination.city}</span>
      </span>
    </p>
  );
}
