/**
 * Static, synthetic presentation fixtures for the public demonstration only.
 *
 * These objects are not domain models, authorization state, API responses, or evidence of
 * a real workflow. Production portal, API, proxy, authentication, and authorization code
 * must never import this module.
 */

export interface DemoLocation {
  readonly iata: string;
  readonly city: string;
}

export const demoFixtures = {
  customer: {
    name: "Demo Customer",
    organization: "Demo Travel Office",
    accessLabel: "Read-only demonstration",
    contact: "Held in the demonstration profile only",
    travelPreferences: "Window seating noted for this demonstration",
    communicationPreferences: "Written notices in this demonstration only",
    securitySummary: "No live session, password, or recovery action is present",
  },
  upcomingTrip: {
    id: "DEMO-TRIP-001",
    route: "Valencia → Paris",
    origin: { iata: "VLC", city: "Valencia" } satisfies DemoLocation,
    destination: { iata: "CDG", city: "Paris" } satisfies DemoLocation,
    departure: "18 September 2026 · 09:30",
    passengers: 4,
    status: "Awaiting confirmation",
    aircraftCategory: "Light jet category",
    organization: "Demo Travel Office",
  },
  bookings: [
    {
      id: "DEMO-BOOKING-001",
      tripId: "DEMO-TRIP-001",
      route: "Valencia → Paris",
      origin: { iata: "VLC", city: "Valencia" } satisfies DemoLocation,
      destination: { iata: "CDG", city: "Paris" } satisfies DemoLocation,
      departure: "18 September 2026 · 09:30",
      passengers: 4,
      aircraftCategory: "Light jet category",
      organization: "Demo Travel Office",
      status: "Awaiting confirmation",
      tone: "warning" as const,
    },
    {
      id: "DEMO-BOOKING-002",
      tripId: "DEMO-TRIP-002",
      route: "Madrid → Geneva",
      origin: { iata: "MAD", city: "Madrid" } satisfies DemoLocation,
      destination: { iata: "GVA", city: "Geneva" } satisfies DemoLocation,
      departure: "3 October 2026 · 14:15",
      passengers: 3,
      aircraftCategory: "Midsize jet category",
      organization: "Demo Travel Office",
      status: "Confirmed",
      tone: "success" as const,
    },
    {
      id: "DEMO-BOOKING-003",
      tripId: "DEMO-TRIP-003",
      route: "Dublin → Nice",
      origin: { iata: "DUB", city: "Dublin" } satisfies DemoLocation,
      destination: { iata: "NCE", city: "Nice" } satisfies DemoLocation,
      departure: "Completed demonstration journey",
      passengers: 5,
      aircraftCategory: "Light jet category",
      organization: "Demo Travel Office",
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
      model: "Demonstration light cabin",
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
      model: "Demonstration midsize cabin",
      departureWindow: "09:30–10:00",
      seats: 8,
      baggage: "Enhanced baggage space",
      estimatedDuration: "1 h 50 min",
    },
  ],
  activity: [
    {
      id: "DEMO-ACTIVITY-001",
      title: "Synthetic trip DEMO-TRIP-001 is awaiting confirmation",
      detail: "Valencia to Paris · demonstration status only",
    },
    {
      id: "DEMO-ACTIVITY-002",
      title: "Synthetic booking DEMO-BOOKING-002 is confirmed",
      detail: "Madrid to Geneva · no live inventory",
    },
    {
      id: "DEMO-ACTIVITY-003",
      title: "Two demonstration offers are available to compare",
      detail: "Selection is not possible in this demonstration",
    },
  ],
} as const;

export const DEMO_DATA_BANNER =
  "Demonstration Preview — synthetic data only. No booking or transaction is created.";
