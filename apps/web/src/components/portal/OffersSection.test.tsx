import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OffersSection } from "@/components/portal/OffersSection";
import type { CustomerOffer } from "@/lib/api/types";

const listTripRequestOffers = vi.fn();
const selectOffer = vi.fn();
vi.mock("@/lib/api/client", () => ({
  portalApi: {
    listTripRequestOffers: (...args: unknown[]) =>
      listTripRequestOffers(...args),
    selectOffer: (...args: unknown[]) => selectOffer(...args),
  },
}));

const makeOffer = (
  status: CustomerOffer["status"],
  currency: CustomerOffer["currency"] = "EUR",
): CustomerOffer => ({
  id: `${status}-${currency}`,
  trip_request_id: "trip",
  status,
  currency,
  total_amount_minor: 123456,
  tax_amount_minor: 1000,
  valid_until: "2099-12-01T00:00:00Z",
  operator_legal_name:
    "A very long factual operator legal name Aviation Limited",
  aircraft_registration: "EI-LONG",
  aircraft_manufacturer: "Bombardier",
  aircraft_model: "Global 7500",
  aircraft_category: "ULTRA_LONG_RANGE",
  included_services: "Catering;Ground transfer",
  excluded_services: "De-icing",
  cancellation_policy:
    "A long factual cancellation policy that must wrap safely without creating an action.",
  created_at: "2026-08-25T00:00:00Z",
  updated_at: "2026-08-25T00:00:00Z",
  response_audience: "customer",
});

beforeEach(() => {
  listTripRequestOffers.mockReset();
  selectOffer.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

async function flushInitialRead() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("OffersSection", () => {
  it("shows loading then an honest empty state", async () => {
    listTripRequestOffers.mockResolvedValueOnce([]);
    render(
      <OffersSection
        tripRequestId="trip"
        tripStatus="SUBMITTED"
        organizationId="org"
      />,
    );
    expect(screen.getByText("Loading published offers…")).toBeTruthy();
    expect(
      await screen.findByText(
        "No published offers are available for this trip request.",
      ),
    ).toBeTruthy();
  });
  it("renders one factual offer with selection but no booking, payment, or ranking claims", async () => {
    listTripRequestOffers.mockResolvedValueOnce([makeOffer("SUBMITTED")]);
    render(
      <OffersSection
        tripRequestId="trip"
        tripStatus="SUBMITTED"
        organizationId="org"
      />,
    );
    expect(await screen.findByText("Available")).toBeTruthy();
    expect(screen.getAllByRole("article")).toHaveLength(1);
    expect(screen.getByText("€1,234.56")).toBeTruthy();
    expect(screen.getByText("EUR")).toBeTruthy();
    expect(
      screen.getByText(
        "A very long factual operator legal name Aviation Limited",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText(/Bombardier Global 7500.*ULTRA_LONG_RANGE.*EI-LONG/),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Select offer" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: /book|pay/i })).toBeNull();
    expect(screen.queryByText(/recommend|best|cheapest|saving/i)).toBeNull();
  });
  it("renders submitted, expired, selected and mixed currencies without actions or fake fields", async () => {
    listTripRequestOffers.mockResolvedValueOnce([
      makeOffer("SELECTED", "USD"),
      makeOffer("EXPIRED", "GBP"),
      makeOffer("SUBMITTED"),
    ]);
    render(
      <OffersSection
        tripRequestId="trip"
        tripStatus="SUBMITTED"
        organizationId="org"
      />,
    );
    expect(await screen.findByText("Available")).toBeTruthy();
    expect(screen.getByText("Expired")).toBeTruthy();
    expect(screen.getByText("Selected")).toBeTruthy();
    expect(screen.getAllByText(/A very long factual/)).toHaveLength(3);
    expect(screen.getAllByRole("article")).toHaveLength(3);
    expect(screen.queryByRole("button", { name: /select/i })).toBeNull();
    expect(
      screen.queryByText(/recommended|capacity|cabin|booking|payment/i),
    ).toBeNull();
  });
  it("isolates offer errors inside the section", async () => {
    listTripRequestOffers.mockRejectedValueOnce(
      new Error("raw backend secret"),
    );
    render(<OffersSection tripRequestId="trip" tripStatus="SUBMITTED" />);
    expect(await screen.findByText("Offers couldn’t be loaded")).toBeTruthy();
    expect(screen.queryByText("raw backend secret")).toBeNull();
  });

  it("requires confirmation, submits once under double click, and locks on authoritative success", async () => {
    const offer = makeOffer("SUBMITTED");
    listTripRequestOffers.mockResolvedValueOnce([offer]);
    let resolveSelection!: (offer: CustomerOffer) => void;
    selectOffer.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveSelection = resolve;
      }),
    );
    render(
      <OffersSection
        tripRequestId="trip"
        tripStatus="SUBMITTED"
        organizationId="org"
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Select offer" }),
    );
    expect(screen.getByText(/does not create a booking/)).toBeTruthy();
    const confirm = screen.getByRole("button", { name: "Select this offer" });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(selectOffer).toHaveBeenCalledTimes(1);
    expect(selectOffer).toHaveBeenCalledWith("trip", offer.id, "org");
    expect(
      screen.getByRole("button", { name: "Keep comparing" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Selecting…" })).toBeDisabled();
    expect(
      screen
        .getByRole("heading", { name: "Confirm offer selection" })
        .closest("section"),
    ).toHaveAttribute("aria-busy", "true");
    resolveSelection({ ...offer, status: "SELECTED" });
    expect(await screen.findByText("Selected")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /select/i })).toBeNull();
  });

  it("handles a 409 without retry and refreshes only on explicit request", async () => {
    const { ApiError } = await import("@/lib/api/errors");
    listTripRequestOffers
      .mockResolvedValueOnce([makeOffer("SUBMITTED")])
      .mockResolvedValueOnce([makeOffer("SELECTED")]);
    selectOffer.mockRejectedValueOnce(
      new ApiError(409, "conflict", "raw secret", "conflict"),
    );
    render(<OffersSection tripRequestId="trip" tripStatus="SUBMITTED" />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Select offer" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Select this offer" }));
    expect(await screen.findByText("Offer selection changed")).toBeTruthy();
    expect(screen.queryByText("raw secret")).toBeNull();
    expect(selectOffer).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Refresh offers" }));
    await waitFor(() => expect(listTripRequestOffers).toHaveBeenCalledTimes(2));
  });

  it("keeps comparing without calling the selection API", async () => {
    listTripRequestOffers.mockResolvedValueOnce([makeOffer("SUBMITTED")]);
    render(<OffersSection tripRequestId="trip" tripStatus="SUBMITTED" />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Select offer" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Keep comparing" }));
    expect(selectOffer).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("heading", { name: "Confirm offer selection" }),
    ).toBeNull();
    expect(screen.getByRole("button", { name: "Select offer" })).toBeTruthy();
  });

  it.each([
    "DRAFT",
    "QUOTING",
    "QUOTES_AVAILABLE",
    "QUOTE_SELECTED",
    "BOOKED",
    "CANCELLED",
    "EXPIRED",
    "FUTURE_TRIP_STATE",
  ])("fails closed for trip status %s", async (tripStatus) => {
    listTripRequestOffers.mockResolvedValueOnce([makeOffer("SUBMITTED")]);
    render(<OffersSection tripRequestId="trip" tripStatus={tripStatus} />);
    expect(await screen.findByText("Available")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Select offer" })).toBeNull();
  });

  it("fails closed for an unknown future offer status", async () => {
    const futureOffer = {
      ...makeOffer("SUBMITTED"),
      status: "FUTURE_OFFER_STATE",
    } as unknown as CustomerOffer;
    listTripRequestOffers.mockResolvedValueOnce([futureOffer]);
    render(<OffersSection tripRequestId="trip" tripStatus="SUBMITTED" />);
    expect(await screen.findByText("Unavailable")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Select offer" })).toBeNull();
  });

  it.each([
    [403, "forbidden"],
    [404, "client"],
    [0, "network"],
    [503, "server"],
  ] as const)(
    "keeps the known offer and hides raw selection error details for status %s",
    async (status, kind) => {
      const { ApiError } = await import("@/lib/api/errors");
      listTripRequestOffers.mockResolvedValueOnce([makeOffer("SUBMITTED")]);
      selectOffer.mockRejectedValueOnce(
        new ApiError(status, "raw_internal_code", "raw backend secret", kind),
      );
      render(<OffersSection tripRequestId="trip" tripStatus="SUBMITTED" />);
      fireEvent.click(
        await screen.findByRole("button", { name: "Select offer" }),
      );
      fireEvent.click(
        screen.getByRole("button", { name: "Select this offer" }),
      );
      expect(
        await screen.findByText("Offer couldn’t be selected"),
      ).toBeTruthy();
      expect(screen.getByText("Available")).toBeTruthy();
      expect(screen.queryByText("Selected")).toBeNull();
      expect(
        screen.queryByText(/raw backend secret|raw_internal_code/),
      ).toBeNull();
      expect(selectOffer).toHaveBeenCalledTimes(1);
    },
  );
});

describe("OffersSection freshness", () => {
  it("polls one GET at the exact 30-second cadence and never mutates", async () => {
    vi.useFakeTimers();
    listTripRequestOffers.mockResolvedValue([makeOffer("SUBMITTED")]);
    render(<OffersSection tripRequestId="trip" tripStatus="SUBMITTED" />);
    await flushInitialRead();
    expect(listTripRequestOffers).toHaveBeenCalledTimes(1);
    await act(() => vi.advanceTimersByTimeAsync(29_999));
    expect(listTripRequestOffers).toHaveBeenCalledTimes(1);
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(listTripRequestOffers).toHaveBeenCalledTimes(2);
    expect(selectOffer).not.toHaveBeenCalled();
  });

  it("does not overlap interval, focus, or manual reads", async () => {
    vi.useFakeTimers();
    let resolveRefresh!: (offers: readonly CustomerOffer[]) => void;
    listTripRequestOffers
      .mockResolvedValueOnce([makeOffer("SUBMITTED")])
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveRefresh = resolve;
        }),
      );
    render(<OffersSection tripRequestId="trip" tripStatus="SUBMITTED" />);
    await flushInitialRead();
    await act(() => vi.advanceTimersByTimeAsync(30_000));
    fireEvent.focus(window);
    fireEvent.click(screen.getByRole("button", { name: "Refreshing…" }));
    await act(() => vi.advanceTimersByTimeAsync(60_000));
    expect(listTripRequestOffers).toHaveBeenCalledTimes(2);
    resolveRefresh([makeOffer("SUBMITTED")]);
    await flushInitialRead();
  });

  it("pauses while hidden and refreshes immediately when visible", async () => {
    vi.useFakeTimers();
    listTripRequestOffers.mockResolvedValue([makeOffer("SUBMITTED")]);
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    render(<OffersSection tripRequestId="trip" tripStatus="SUBMITTED" />);
    await flushInitialRead();
    hidden.mockReturnValue(true);
    fireEvent(document, new Event("visibilitychange"));
    await act(() => vi.advanceTimersByTimeAsync(60_000));
    expect(listTripRequestOffers).toHaveBeenCalledTimes(1);
    hidden.mockReturnValue(false);
    fireEvent(document, new Event("visibilitychange"));
    await flushInitialRead();
    expect(listTripRequestOffers).toHaveBeenCalledTimes(2);
  });

  it("refreshes immediately on focus only while eligible", async () => {
    listTripRequestOffers.mockResolvedValue([makeOffer("SUBMITTED")]);
    const { rerender } = render(
      <OffersSection tripRequestId="trip" tripStatus="SUBMITTED" />,
    );
    await flushInitialRead();
    fireEvent.focus(window);
    await waitFor(() => expect(listTripRequestOffers).toHaveBeenCalledTimes(2));
    rerender(<OffersSection tripRequestId="trip" tripStatus="CANCELLED" />);
    fireEvent.focus(window);
    await flushInitialRead();
    expect(listTripRequestOffers).toHaveBeenCalledTimes(2);
  });

  it("stops automatic polling when an offer is selected", async () => {
    vi.useFakeTimers();
    listTripRequestOffers.mockResolvedValue([makeOffer("SELECTED")]);
    render(<OffersSection tripRequestId="trip" tripStatus="SUBMITTED" />);
    await flushInitialRead();
    await act(() => vi.advanceTimersByTimeAsync(90_000));
    expect(listTripRequestOffers).toHaveBeenCalledTimes(1);
  });

  it("clears the polling interval after authoritative selection success", async () => {
    vi.useFakeTimers();
    const offer = makeOffer("SUBMITTED");
    listTripRequestOffers.mockResolvedValue([offer]);
    selectOffer.mockResolvedValue({ ...offer, status: "SELECTED" });
    render(<OffersSection tripRequestId="trip" tripStatus="SUBMITTED" />);
    await flushInitialRead();
    fireEvent.click(screen.getByRole("button", { name: "Select offer" }));
    fireEvent.click(screen.getByRole("button", { name: "Select this offer" }));
    await flushInitialRead();
    expect(screen.getByText("Selected")).toBeTruthy();
    await act(() => vi.advanceTimersByTimeAsync(90_000));
    expect(listTripRequestOffers).toHaveBeenCalledTimes(1);
  });

  it.each(["DRAFT", "CANCELLED", "EXPIRED", "FUTURE_STATE"])(
    "does not poll for non-SUBMITTED status %s",
    async (status) => {
      vi.useFakeTimers();
      listTripRequestOffers.mockResolvedValue([makeOffer("SUBMITTED")]);
      render(<OffersSection tripRequestId="trip" tripStatus={status} />);
      await flushInitialRead();
      await act(() => vi.advanceTimersByTimeAsync(90_000));
      expect(listTripRequestOffers).toHaveBeenCalledTimes(1);
    },
  );

  it("aborts the active read on unmount", async () => {
    listTripRequestOffers.mockReturnValue(new Promise(() => undefined));
    const { unmount } = render(
      <OffersSection tripRequestId="trip" tripStatus="SUBMITTED" />,
    );
    await flushInitialRead();
    const signal = listTripRequestOffers.mock.calls[0][2] as AbortSignal;
    expect(signal.aborted).toBe(false);
    unmount();
    expect(signal.aborted).toBe(true);
  });

  it("prevents an obsolete read from replacing the new identity after it resolves last", async () => {
    let resolveOld!: (offers: readonly CustomerOffer[]) => void;
    let resolveNew!: (offers: readonly CustomerOffer[]) => void;
    listTripRequestOffers
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveOld = resolve;
        }),
      )
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveNew = resolve;
        }),
      );
    const { rerender } = render(
      <OffersSection
        tripRequestId="trip-a"
        tripStatus="SUBMITTED"
        organizationId="org-a"
      />,
    );
    await flushInitialRead();
    const staleSignal = listTripRequestOffers.mock.calls[0][2] as AbortSignal;
    rerender(
      <OffersSection
        tripRequestId="trip-b"
        tripStatus="SUBMITTED"
        organizationId="org-b"
      />,
    );
    await flushInitialRead();
    expect(staleSignal.aborted).toBe(true);
    expect(listTripRequestOffers).toHaveBeenLastCalledWith(
      "trip-b",
      "org-b",
      expect.anything(),
    );
    resolveNew([
      {
        ...makeOffer("SUBMITTED"),
        id: "new-b",
        aircraft_registration: "NEW-B",
      },
    ]);
    expect(
      await screen.findByText(
        (_, element) =>
          element?.tagName === "DD" &&
          element.textContent?.includes("NEW-B") === true,
      ),
    ).toBeTruthy();
    resolveOld([
      {
        ...makeOffer("SUBMITTED"),
        id: "old-a",
        aircraft_registration: "OLD-A",
      },
    ]);
    await flushInitialRead();
    expect(
      screen.getByText(
        (_, element) =>
          element?.tagName === "DD" &&
          element.textContent?.includes("NEW-B") === true,
      ),
    ).toBeTruthy();
    expect(
      screen.queryByText(
        (_, element) =>
          element?.tagName === "DD" &&
          element.textContent?.includes("OLD-A") === true,
      ),
    ).toBeNull();
  });

  it("retains known data and safe copy after a transient refresh failure", async () => {
    listTripRequestOffers
      .mockResolvedValueOnce([makeOffer("SUBMITTED")])
      .mockRejectedValueOnce(new Error("raw refresh secret"));
    render(<OffersSection tripRequestId="trip" tripStatus="SUBMITTED" />);
    expect(await screen.findByText("Available")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Refresh offers" }));
    expect(
      await screen.findByText(
        "Couldn’t refresh offers. Showing the last known information.",
      ),
    ).toBeTruthy();
    expect(screen.getByText("Available")).toBeTruthy();
    expect(screen.queryByText("raw refresh secret")).toBeNull();
  });

  it("announces one failure state until recovery, then permits a later new announcement", async () => {
    listTripRequestOffers
      .mockResolvedValueOnce([makeOffer("SUBMITTED")])
      .mockRejectedValueOnce(new Error("first raw secret"))
      .mockRejectedValueOnce(new Error("repeated raw secret"))
      .mockResolvedValueOnce([makeOffer("SUBMITTED")])
      .mockRejectedValueOnce(new Error("later raw secret"));
    render(<OffersSection tripRequestId="trip" tripStatus="SUBMITTED" />);
    expect(await screen.findByText("Available")).toBeTruthy();
    const refresh = screen.getByRole("button", { name: "Refresh offers" });

    fireEvent.click(refresh);
    const firstWarning = await screen.findByRole("status", {
      name: "",
    });
    expect(firstWarning).toHaveTextContent(
      "Couldn’t refresh offers. Showing the last known information.",
    );
    expect(screen.getByText("Available")).toBeTruthy();

    fireEvent.click(refresh);
    await waitFor(() => expect(listTripRequestOffers).toHaveBeenCalledTimes(3));
    expect(
      screen
        .getByText(
          "Couldn’t refresh offers. Showing the last known information.",
        )
        .closest('[role="status"]'),
    ).toBe(firstWarning);

    fireEvent.click(refresh);
    await waitFor(() => expect(firstWarning).not.toBeInTheDocument());
    fireEvent.click(refresh);
    const laterWarning = await screen.findByText(
      "Couldn’t refresh offers. Showing the last known information.",
    );
    expect(laterWarning.closest('[role="status"]')).not.toBe(firstWarning);
    expect(screen.getByText("Available")).toBeTruthy();
    expect(
      screen.queryByText(
        /first raw secret|repeated raw secret|later raw secret/,
      ),
    ).toBeNull();
  });

  it("deduplicates manual double-click and disables the action in flight", async () => {
    let resolveRefresh!: (offers: readonly CustomerOffer[]) => void;
    listTripRequestOffers
      .mockResolvedValueOnce([makeOffer("SUBMITTED")])
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveRefresh = resolve;
        }),
      );
    render(<OffersSection tripRequestId="trip" tripStatus="SUBMITTED" />);
    await screen.findByText("Available");
    const refresh = screen.getByRole("button", { name: "Refresh offers" });
    fireEvent.click(refresh);
    fireEvent.click(refresh);
    expect(listTripRequestOffers).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: "Refreshing…" })).toBeDisabled();
    resolveRefresh([makeOffer("SUBMITTED")]);
    await flushInitialRead();
  });

  it("replaces an expired offer authoritatively and removes Select", async () => {
    listTripRequestOffers
      .mockResolvedValueOnce([makeOffer("SUBMITTED")])
      .mockResolvedValueOnce([makeOffer("EXPIRED")]);
    render(<OffersSection tripRequestId="trip" tripStatus="SUBMITTED" />);
    expect(
      await screen.findByRole("button", { name: "Select offer" }),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Refresh offers" }));
    expect(await screen.findByText("Expired")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Select offer" })).toBeNull();
  });
});
