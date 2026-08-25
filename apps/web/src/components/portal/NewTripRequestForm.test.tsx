import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NewTripRequestForm } from "@/components/portal/NewTripRequestForm";
import { ApiError } from "@/lib/api/errors";
import type { Airport, CustomerTripRequest } from "@/lib/api/types";

const A1 = "11111111-1111-4111-8111-111111111111";
const A2 = "22222222-2222-4222-8222-222222222222";
const TRIP_ID = "b32413c8-88e9-4c05-89e5-78afb14f5eb4";

const listAirports = vi.fn();
const createPassenger = vi.fn();
const createTripRequest = vi.fn();
const submitTripRequest = vi.fn();

vi.mock("@/lib/api/client", () => ({
  portalApi: {
    listAirports: (...a: unknown[]) => listAirports(...a),
    createPassenger: (...a: unknown[]) => createPassenger(...a),
    createTripRequest: (...a: unknown[]) => createTripRequest(...a),
    submitTripRequest: (...a: unknown[]) => submitTripRequest(...a),
  },
}));

let orgContext = {
  activeOrganizationId: "org-1" as string | null,
  hasCustomerContext: true,
};
vi.mock("@/components/session/org-context", () => ({
  useActiveOrganization: () => orgContext,
}));

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

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

function trip(status: string, version: number): CustomerTripRequest {
  return {
    id: TRIP_ID,
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

beforeEach(() => {
  orgContext = { activeOrganizationId: "org-1", hasCustomerContext: true };
  listAirports.mockReset().mockResolvedValue(AIRPORTS);
  createPassenger.mockReset();
  createTripRequest.mockReset();
  submitTripRequest.mockReset();
  push.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

/** Select an airport in the named combobox by typing and clicking the matching option. */
function pickAirport(comboName: string, query: string, optionMatch: RegExp) {
  const input = screen.getByRole("combobox", { name: comboName });
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value: query } });
  fireEvent.mouseDown(screen.getByRole("option", { name: optionMatch }));
}

async function fillValidForm() {
  // Airports are loaded asynchronously; wait for the combobox to appear.
  await screen.findByRole("combobox", { name: "From" });
  pickAirport("From", "dub", /Dublin/);
  pickAirport("To", "lon", /Heathrow/);
  fireEvent.change(screen.getByLabelText("Departure"), {
    target: { value: "2027-01-01T10:00" },
  });
  fireEvent.change(screen.getByLabelText("First name"), {
    target: { value: "Ada" },
  });
  fireEvent.change(screen.getByLabelText("Last name"), {
    target: { value: "Byron" },
  });
}

function primaryButton(): HTMLButtonElement {
  return screen.getByRole("button", {
    name: /Create & submit request|Try again|Retry submission|…/,
  });
}

describe("NewTripRequestForm — happy path", () => {
  it("creates a passenger, a DRAFT, submits, and navigates; no customer_id sent", async () => {
    createPassenger.mockResolvedValueOnce({
      id: "p1",
      first_name: "Ada",
      last_name: "Byron",
    });
    createTripRequest.mockResolvedValueOnce(trip("DRAFT", 1));
    submitTripRequest.mockResolvedValueOnce(trip("SUBMITTED", 2));

    render(<NewTripRequestForm />);
    await fillValidForm();
    fireEvent.click(primaryButton());

    await waitFor(() =>
      expect(push).toHaveBeenCalledWith(`/portal/trip-requests/${TRIP_ID}`),
    );
    // Passenger body carries no customer_id.
    const passengerBody = createPassenger.mock.calls[0][0] as Record<
      string,
      unknown
    >;
    expect("customer_id" in passengerBody).toBe(false);
    // Trip body carries no customer_id and references the created passenger id.
    const tripBody = createTripRequest.mock.calls[0][0] as {
      passenger_ids: string[];
      legs: { origin_airport_id: string; destination_airport_id: string }[];
    };
    expect(JSON.stringify(tripBody)).not.toContain("customer_id");
    expect(tripBody.passenger_ids).toEqual(["p1"]);
    expect(tripBody.legs[0]).toMatchObject({
      origin_airport_id: A1,
      destination_airport_id: A2,
    });
    // Submit used the DRAFT id + returned version.
    expect(submitTripRequest).toHaveBeenCalledWith(
      TRIP_ID,
      1,
      "org-1",
      undefined,
    );
  });

  it("prevents a double-click from creating two passengers or two trips", async () => {
    let resolvePassenger: (v: unknown) => void = () => {};
    createPassenger.mockReturnValueOnce(
      new Promise((resolve) => {
        resolvePassenger = resolve;
      }),
    );
    createTripRequest.mockResolvedValueOnce(trip("DRAFT", 1));
    submitTripRequest.mockResolvedValueOnce(trip("SUBMITTED", 2));

    render(<NewTripRequestForm />);
    await fillValidForm();
    const button = primaryButton();
    fireEvent.click(button);
    fireEvent.click(button); // second, overlapping click
    resolvePassenger({ id: "p1", first_name: "Ada", last_name: "Byron" });

    await waitFor(() => expect(push).toHaveBeenCalled());
    expect(createPassenger).toHaveBeenCalledTimes(1);
    expect(createTripRequest).toHaveBeenCalledTimes(1);
    expect(submitTripRequest).toHaveBeenCalledTimes(1);
  });
});

describe("NewTripRequestForm — partial failures & retries", () => {
  it("passenger failure then retry reuses no passenger id and creates it once more", async () => {
    createPassenger
      .mockRejectedValueOnce(new ApiError(409, "c", "raw", "conflict"))
      .mockResolvedValueOnce({
        id: "p1",
        first_name: "Ada",
        last_name: "Byron",
      });
    createTripRequest.mockResolvedValueOnce(trip("DRAFT", 1));
    submitTripRequest.mockResolvedValueOnce(trip("SUBMITTED", 2));

    render(<NewTripRequestForm />);
    await fillValidForm();
    fireEvent.click(primaryButton());

    expect(await screen.findByText(/save the passenger details/i)).toBeTruthy();
    // Retry.
    fireEvent.click(primaryButton());
    await waitFor(() => expect(push).toHaveBeenCalled());
    expect(createPassenger).toHaveBeenCalledTimes(2); // one failed + one retry
    expect(createTripRequest).toHaveBeenCalledTimes(1);
  });

  it("trip-create failure then retry does NOT recreate the passenger", async () => {
    createPassenger.mockResolvedValueOnce({
      id: "p1",
      first_name: "Ada",
      last_name: "Byron",
    });
    createTripRequest
      .mockRejectedValueOnce(new ApiError(409, "c", "raw", "conflict"))
      .mockResolvedValueOnce(trip("DRAFT", 1));
    submitTripRequest.mockResolvedValueOnce(trip("SUBMITTED", 2));

    render(<NewTripRequestForm />);
    await fillValidForm();
    fireEvent.click(primaryButton());

    expect(await screen.findByText(/create your trip request/i)).toBeTruthy();
    fireEvent.click(primaryButton());
    await waitFor(() => expect(push).toHaveBeenCalled());
    expect(createPassenger).toHaveBeenCalledTimes(1); // reused
    expect(createTripRequest).toHaveBeenCalledTimes(2);
    expect(submitTripRequest).toHaveBeenCalledTimes(1);
  });

  it("submit failure then retry submits the SAME DRAFT — never a second trip", async () => {
    createPassenger.mockResolvedValueOnce({
      id: "p1",
      first_name: "Ada",
      last_name: "Byron",
    });
    createTripRequest.mockResolvedValueOnce(trip("DRAFT", 1));
    submitTripRequest
      .mockRejectedValueOnce(new ApiError(409, "conflict", "raw", "conflict"))
      .mockResolvedValueOnce(trip("SUBMITTED", 2));

    render(<NewTripRequestForm />);
    await fillValidForm();
    fireEvent.click(primaryButton());

    expect(
      await screen.findByText(/changed while it was being submitted/i),
    ).toBeTruthy();
    fireEvent.click(primaryButton());
    await waitFor(() => expect(push).toHaveBeenCalled());
    expect(createTripRequest).toHaveBeenCalledTimes(1); // never a second DRAFT
    expect(createPassenger).toHaveBeenCalledTimes(1);
    expect(submitTripRequest).toHaveBeenCalledTimes(2);
    // Retry submitted the same id and the returned version.
    expect(submitTripRequest).toHaveBeenNthCalledWith(
      2,
      TRIP_ID,
      1,
      "org-1",
      undefined,
    );
  });

  it("never surfaces a raw backend message on submit failure", async () => {
    createPassenger.mockResolvedValueOnce({
      id: "p1",
      first_name: "Ada",
      last_name: "Byron",
    });
    createTripRequest.mockResolvedValueOnce(trip("DRAFT", 1));
    submitTripRequest.mockRejectedValueOnce(
      new ApiError(500, "server_error", "SECRET-STACK-TRACE", "server"),
    );

    render(<NewTripRequestForm />);
    await fillValidForm();
    fireEvent.click(primaryButton());

    expect(await screen.findByText(/Not submitted yet/i)).toBeTruthy();
    expect(screen.queryByText(/SECRET-STACK-TRACE/)).toBeNull();
  });
});

describe("NewTripRequestForm — validation, context, and no forbidden controls", () => {
  it("shows field errors and calls no API when the form is empty", async () => {
    render(<NewTripRequestForm />);
    await screen.findByRole("combobox", { name: "From" });
    fireEvent.click(primaryButton());
    expect(await screen.findByText("Select a departure airport.")).toBeTruthy();
    expect(createPassenger).not.toHaveBeenCalled();
    expect(createTripRequest).not.toHaveBeenCalled();
  });

  it("prompts to link a customer account when there is no customer context", () => {
    orgContext = { activeOrganizationId: null, hasCustomerContext: false };
    render(<NewTripRequestForm />);
    expect(screen.getByText("No active customer account")).toBeTruthy();
    expect(listAirports).not.toHaveBeenCalled();
  });

  it("has no cancel / offer / booking / payment controls", async () => {
    render(<NewTripRequestForm />);
    await screen.findByRole("combobox", { name: "From" });
    for (const name of [/cancel/i, /offer/i, /book/i, /pay/i]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
  });
});
