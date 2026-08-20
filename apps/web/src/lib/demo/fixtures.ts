/**
 * Static, synthetic presentation fixtures for the public demonstration only.
 *
 * These objects are not domain models, authorization state, API responses, or evidence of
 * a real workflow. Production portal, API, proxy, authentication, and authorization code
 * must never import this module.
 */

export const demoFixtures = {
  customer: {
    name: "Demo Customer",
    organization: "Demo Travel Office",
    accessLabel: "Read-only demonstration",
  },
  upcomingTrip: {
    id: "DEMO-TRIP-001",
    route: "Valencia → Paris",
    departure: "18 September 2026 · 09:30",
    passengers: 4,
  },
  bookings: [
    {
      id: "DEMO-BOOKING-001",
      tripId: "DEMO-TRIP-001",
      route: "Valencia → Paris",
      departure: "18 September 2026 · 09:30",
      status: "Awaiting confirmation",
      tone: "warning" as const,
    },
    {
      id: "DEMO-BOOKING-002",
      tripId: "DEMO-TRIP-002",
      route: "Madrid → Geneva",
      departure: "3 October 2026 · 14:15",
      status: "Confirmed",
      tone: "success" as const,
    },
    {
      id: "DEMO-BOOKING-003",
      tripId: "DEMO-TRIP-003",
      route: "Dublin → Nice",
      departure: "Completed demonstration journey",
      status: "Completed",
      tone: "neutral" as const,
    },
  ],
  offers: [
    {
      id: "DEMO-OFFER-001",
      tripId: "DEMO-TRIP-001",
      label: "Demonstration option A",
      category: "Light jet category",
      departureWindow: "09:15–09:45",
      seats: 6,
      baggage: "Standard cabin baggage",
      estimatedDuration: "1 h 55 min",
    },
    {
      id: "DEMO-OFFER-002",
      tripId: "DEMO-TRIP-001",
      label: "Demonstration option B",
      category: "Midsize jet category",
      departureWindow: "09:30–10:00",
      seats: 8,
      baggage: "Enhanced baggage space",
      estimatedDuration: "1 h 50 min",
    },
  ],
} as const;

export const DEMO_DATA_BANNER =
  "Demonstration Preview — synthetic data only. No booking or transaction is created.";
