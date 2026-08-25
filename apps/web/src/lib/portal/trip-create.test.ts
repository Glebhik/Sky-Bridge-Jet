import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/errors";
import type {
  Airport,
  CustomerTripRequest,
  PassengerRecord,
} from "@/lib/api/types";
import {
  buildPassengerPayload,
  buildProgress,
  buildTripPayload,
  emptyForm,
  filterAirports,
  messageForSubmitError,
  normalizeDeparture,
  runCreation,
  validateForm,
  type CreationApi,
  type TripRequestForm,
} from "@/lib/portal/trip-create";

const A1 = "11111111-1111-4111-8111-111111111111";
const A2 = "22222222-2222-4222-8222-222222222222";

function validForm(): TripRequestForm {
  return {
    ...emptyForm(),
    origin_airport_id: A1,
    destination_airport_id: A2,
    departure_at_local: "2027-01-01T10:00",
    passengers: [
      {
        first_name: "Ada",
        last_name: "Byron",
        date_of_birth: "",
        nationality: "gb",
        contact_email: "",
        contact_phone: "",
      },
    ],
    requirements: {
      baggage_notes: "",
      catering_notes: "",
      special_assistance_notes: "",
      customer_notes: "  keep me  ",
      ground_transport_requested: true,
    },
  };
}

const AIRPORTS: readonly Airport[] = [
  {
    id: A1,
    icao_code: "EIDW",
    iata_code: "DUB",
    name: "Dublin",
    city: "Dublin",
    country_code: "IE",
  },
  {
    id: A2,
    icao_code: "EGLL",
    iata_code: "LHR",
    name: "Heathrow",
    city: "London",
    country_code: "GB",
  },
];

describe("payload builders — never include customer_id", () => {
  it("buildPassengerPayload omits customer_id and normalizes optionals", () => {
    const payload = buildPassengerPayload(validForm().passengers[0]);
    expect("customer_id" in payload).toBe(false);
    expect(JSON.stringify(payload)).not.toContain("customer_id");
    expect(payload).toEqual({
      first_name: "Ada",
      last_name: "Byron",
      date_of_birth: null,
      nationality: "GB",
      contact_email: null,
      contact_phone: null,
    });
  });

  it("buildTripPayload omits customer_id and sets a single leg with the roster count", () => {
    const payload = buildTripPayload(validForm(), ["p1", "p2"]);
    expect("customer_id" in payload).toBe(false);
    expect(JSON.stringify(payload)).not.toContain("customer_id");
    expect(payload.legs).toHaveLength(1);
    expect(payload.legs[0]).toMatchObject({
      origin_airport_id: A1,
      destination_airport_id: A2,
      passenger_count: 2,
    });
    // departure normalized to a timezone-aware ISO (ends with Z).
    expect(payload.legs[0].departure_at.endsWith("Z")).toBe(true);
    expect(payload.passenger_ids).toEqual(["p1", "p2"]);
    expect(payload.requirements.customer_notes).toBe("keep me");
    expect(payload.requirements.ground_transport_requested).toBe(true);
  });
});

describe("validateForm — client-convenience rules only", () => {
  it("passes a valid form", () => {
    expect(validateForm(validForm())).toEqual({});
  });

  it("requires both airports, different, a departure, and passenger names", () => {
    const errors = validateForm({
      ...emptyForm(),
      origin_airport_id: A1,
      destination_airport_id: A1, // same as origin
      departure_at_local: "",
      passengers: [
        {
          first_name: "",
          last_name: "",
          date_of_birth: "",
          nationality: "",
          contact_email: "",
          contact_phone: "",
        },
      ],
    });
    expect(errors.destination).toBeTruthy();
    expect(errors.departure).toBeTruthy();
    expect(errors["passenger.0.first_name"]).toBeTruthy();
    expect(errors["passenger.0.last_name"]).toBeTruthy();
  });
});

describe("normalizeDeparture / filterAirports", () => {
  it("normalizes a local datetime to a tz-aware ISO and rejects junk", () => {
    expect(normalizeDeparture("2027-01-01T10:00")?.endsWith("Z")).toBe(true);
    expect(normalizeDeparture("")).toBeNull();
    expect(normalizeDeparture("not-a-date")).toBeNull();
  });

  it("filters by city, name, IATA and ICAO; empty query returns a slice", () => {
    expect(filterAirports(AIRPORTS, "lon")).toHaveLength(1);
    expect(filterAirports(AIRPORTS, "LHR")[0].id).toBe(A2);
    expect(filterAirports(AIRPORTS, "eidw")[0].id).toBe(A1);
    expect(filterAirports(AIRPORTS, "")).toHaveLength(2);
    expect(filterAirports(AIRPORTS, "zzz")).toHaveLength(0);
  });
});

// ── Orchestrator: a controllable fake API that counts calls ─────────────────────────────────
function fakeApi(overrides: Partial<CreationApi> = {}): {
  api: CreationApi;
  calls: { passenger: number; trip: number; submit: number };
} {
  const calls = { passenger: 0, trip: 0, submit: 0 };
  let passengerSeq = 0;
  const api: CreationApi = {
    createPassenger: vi.fn(async (): Promise<PassengerRecord> => {
      calls.passenger += 1;
      passengerSeq += 1;
      return { id: `p${passengerSeq}`, first_name: "A", last_name: "B" };
    }),
    createTripRequest: vi.fn(async (): Promise<CustomerTripRequest> => {
      calls.trip += 1;
      return trip("DRAFT", 1);
    }),
    submitTripRequest: vi.fn(async (): Promise<CustomerTripRequest> => {
      calls.submit += 1;
      return trip("SUBMITTED", 2);
    }),
    ...overrides,
  };
  return { api, calls };
}

function trip(status: string, version: number): CustomerTripRequest {
  return {
    id: "b32413c8-88e9-4c05-89e5-78afb14f5eb4",
    status,
    version,
    legs: [],
    passengers: [],
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
  };
}

describe("runCreation — happy path and idempotent retries", () => {
  it("creates passengers, one DRAFT, then submits, in order", async () => {
    const { api, calls } = fakeApi();
    const progress = buildProgress(validForm(), "org-1");
    const phases: string[] = [];
    const result = await runCreation(api, progress, (p) => phases.push(p));
    expect(result.status).toBe("SUBMITTED");
    expect(calls).toEqual({ passenger: 1, trip: 1, submit: 1 });
    expect(phases).toEqual([
      "creating_passengers",
      "creating_trip",
      "submitting_trip",
      "submitted",
    ]);
    expect(progress.passengers[0].id).toBe("p1");
    expect(progress.draft).toMatchObject({ version: 2 });
  });

  it("submit failure then retry submits the SAME DRAFT — no new passenger or trip", async () => {
    let submitAttempts = 0;
    const { api, calls } = fakeApi({
      submitTripRequest: vi.fn(async () => {
        submitAttempts += 1;
        calls.submit += 1;
        if (submitAttempts === 1) {
          throw new ApiError(409, "conflict", "x", "conflict");
        }
        return trip("SUBMITTED", 2);
      }),
    });
    const progress = buildProgress(validForm(), "org-1");
    await expect(runCreation(api, progress, () => {})).rejects.toBeInstanceOf(
      ApiError,
    );
    expect(progress.draft).not.toBeNull();
    // Retry with the same progress.
    const result = await runCreation(api, progress, () => {});
    expect(result.status).toBe("SUBMITTED");
    expect(calls.passenger).toBe(1); // not recreated
    expect(calls.trip).toBe(1); // not recreated
    expect(calls.submit).toBe(2); // submit retried
  });

  it("trip-create failure then retry reuses passengers — no duplicate passengers", async () => {
    let tripAttempts = 0;
    const { api, calls } = fakeApi({
      createTripRequest: vi.fn(async () => {
        tripAttempts += 1;
        calls.trip += 1;
        if (tripAttempts === 1) throw new ApiError(409, "c", "x", "conflict");
        return trip("DRAFT", 1);
      }),
    });
    const progress = buildProgress(validForm(), "org-1");
    await expect(runCreation(api, progress, () => {})).rejects.toBeTruthy();
    expect(progress.passengers[0].id).toBe("p1");
    expect(progress.draft).toBeNull();
    const result = await runCreation(api, progress, () => {});
    expect(result.status).toBe("SUBMITTED");
    expect(calls.passenger).toBe(1); // reused, not recreated
    expect(calls.trip).toBe(2);
    expect(calls.submit).toBe(1);
  });

  it("partial passenger failure retry only creates the missing passenger", async () => {
    const form = {
      ...validForm(),
      passengers: [
        validForm().passengers[0],
        { ...validForm().passengers[0], first_name: "Grace" },
      ],
    };
    let attempts = 0;
    const { api, calls } = fakeApi({
      createPassenger: vi.fn(async () => {
        attempts += 1;
        calls.passenger += 1;
        // First passenger succeeds, second fails on the first attempt.
        if (attempts === 2) throw new ApiError(409, "c", "x", "conflict");
        return {
          id: `p${attempts}`,
          first_name: "A",
          last_name: "B",
        } as PassengerRecord;
      }),
    });
    const progress = buildProgress(form, "org-1");
    await expect(runCreation(api, progress, () => {})).rejects.toBeTruthy();
    expect(progress.passengers[0].id).toBe("p1");
    expect(progress.passengers[1].id).toBeNull();
    // Retry: only the second passenger is created (call count grows by exactly 1).
    const result = await runCreation(api, progress, () => {});
    expect(result.status).toBe("SUBMITTED");
    expect(calls.passenger).toBe(3); // 2 failed-run calls + 1 retry call
    expect(progress.passengers[1].id).not.toBeNull();
    expect(calls.trip).toBe(1);
  });

  it("throws if the create response is not a DRAFT (state-machine assertion)", async () => {
    const { api } = fakeApi({
      createTripRequest: vi.fn(async () => trip("SUBMITTED", 1)),
    });
    const progress = buildProgress(validForm(), "org-1");
    await expect(runCreation(api, progress, () => {})).rejects.toThrow(/DRAFT/);
  });
});

describe("messageForSubmitError — safe, status-specific", () => {
  it("uses a conflict message on 409 and a generic one otherwise", () => {
    expect(
      messageForSubmitError(new ApiError(409, "c", "raw", "conflict")),
    ).toMatch(/changed while it was being submitted/);
    expect(
      messageForSubmitError(new ApiError(500, "s", "raw-secret", "server")),
    ).not.toContain("raw-secret");
  });
});
