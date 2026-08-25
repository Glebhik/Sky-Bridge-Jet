import { describe, expect, it } from "vitest";

import type { Airport, CustomerTripRequest } from "@/lib/api/types";
import {
  airportLabel,
  firstDeparture,
  legSummary,
  tripHandle,
  tripStatusTone,
} from "@/lib/portal/trip-requests";

function trip(
  overrides: Partial<CustomerTripRequest> = {},
): CustomerTripRequest {
  return {
    id: "b32413c8-88e9-4c05-89e5-78afb14f5eb4",
    status: "SUBMITTED",
    version: 1,
    legs: [
      {
        id: "leg-2",
        sequence: 2,
        origin_airport_id: "a2",
        destination_airport_id: "a3",
        departure_at: "2026-09-02T09:00:00Z",
        origin_timezone: "Europe/London",
        destination_timezone: "Europe/Paris",
        passenger_count: 2,
      },
      {
        id: "leg-1",
        sequence: 1,
        origin_airport_id: "a1",
        destination_airport_id: "a2",
        departure_at: "2026-09-01T08:00:00Z",
        origin_timezone: "Europe/Dublin",
        destination_timezone: "Europe/London",
        passenger_count: 2,
      },
    ],
    passengers: [{ id: "p1", first_name: "Ada", last_name: "Byron" }],
    requirements: {
      baggage_notes: null,
      catering_notes: null,
      ground_transport_requested: false,
      special_assistance_notes: null,
      customer_notes: null,
      pet_present: false,
    },
    created_at: "2026-08-25T00:00:00Z",
    updated_at: "2026-08-25T00:00:00Z",
    ...overrides,
  };
}

describe("tripStatusTone", () => {
  it("maps known statuses to tones and falls back to neutral", () => {
    expect(tripStatusTone("BOOKED")).toBe("success");
    expect(tripStatusTone("CANCELLED")).toBe("danger");
    expect(tripStatusTone("EXPIRED")).toBe("warning");
    expect(tripStatusTone("SUBMITTED")).toBe("info");
    expect(tripStatusTone("DRAFT")).toBe("neutral");
    expect(tripStatusTone("SOME_FUTURE_STATUS")).toBe("neutral");
  });
});

describe("tripHandle", () => {
  it("derives a short handle from the real UUID (no fabricated code)", () => {
    expect(tripHandle("b32413c8-88e9-4c05-89e5-78afb14f5eb4")).toBe(
      "Request B32413C8",
    );
  });
});

describe("firstDeparture / legSummary", () => {
  it("uses the earliest leg by sequence, not array order", () => {
    expect(firstDeparture(trip().legs)).toBe("2026-09-01T08:00:00Z");
    expect(legSummary(trip())).toContain("2 legs");
    expect(legSummary(trip({ legs: [trip().legs[1]] }))).toContain("1 leg");
  });
});

describe("airportLabel", () => {
  it("prefers a resolved airport (city + code) over the timezone fallback", () => {
    const airport: Airport = {
      id: "a1",
      icao_code: "EIDW",
      iata_code: "DUB",
      name: "Dublin",
      city: "Dublin",
      country_code: "IE",
    };
    expect(airportLabel(airport, "Europe/Dublin")).toBe("Dublin (DUB)");
  });

  it("falls back to the timezone when the airport is unresolved", () => {
    expect(airportLabel(undefined, "Europe/Dublin")).toBe("Europe/Dublin");
  });

  it("uses ICAO when a resolved airport has no IATA code", () => {
    const airport: Airport = {
      id: "a1",
      icao_code: "EIDW",
      iata_code: null,
      name: "Dublin",
      city: "Dublin",
      country_code: "IE",
    };
    expect(airportLabel(airport, "Europe/Dublin")).toBe("Dublin (EIDW)");
  });
});
