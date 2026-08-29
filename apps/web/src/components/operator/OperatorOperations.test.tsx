import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OperatorOperations } from "@/components/operator/OperatorOperations";
import { ApiError } from "@/lib/api/errors";
import type { OperatorFlightOperation } from "@/lib/api/types";

const listOperations = vi.fn();
const getOperation = vi.fn();
vi.mock("@/lib/api/client", () => ({
  portalApi: {
    listOperatorOperations: (...args: unknown[]) => listOperations(...args),
    getOperatorOperation: (...args: unknown[]) => getOperation(...args),
  },
}));

const organizations = [
  { id: "org-a", role: "OPERATOR_ADMIN" },
  { id: "org-b", role: "OPERATOR_FINANCE" },
];
const item = (
  suffix: string,
  bookingStatus = "CONFIRMED",
): OperatorFlightOperation => ({
  operation_id: `11111111-2222-4333-8444-55555555555${suffix}`,
  booking_id: `21111111-2222-4333-8444-55555555555${suffix}`,
  booking_reference: `SBJ-${suffix}`,
  status: "HANDOFF_CREATED",
  booking_status: bookingStatus as OperatorFlightOperation["booking_status"],
  aircraft_registration: `EI-${suffix}`,
  aircraft_manufacturer: "Cessna",
  aircraft_model: "Citation",
  aircraft_category: "LIGHT_JET",
  legs: [
    {
      sequence: 1,
      origin_airport_code: "EIDW",
      destination_airport_code: "EGLL",
      departure_at: "2026-09-01T10:00:00Z",
      passenger_count: 3,
    },
  ],
  created_at: "2026-08-29T10:00:00Z",
  updated_at: "2026-08-29T10:00:00Z",
});

beforeEach(() => {
  listOperations.mockReset();
  getOperation.mockReset();
});

describe("OperatorOperations", () => {
  it("requires explicit multi-org selection and renders a bounded factual page", async () => {
    listOperations.mockResolvedValue([item("1")]);
    render(<OperatorOperations organizations={organizations} />);
    expect(screen.getAllByText("Choose operator organization")).toHaveLength(2);
    expect(listOperations).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(/Operator organization/), {
      target: { value: "org-a" },
    });
    expect(await screen.findByText("SBJ-1")).toBeTruthy();
    expect(listOperations).toHaveBeenCalledWith(
      "org-a",
      { limit: 20, offset: 0 },
      expect.any(AbortSignal),
    );
    expect(screen.getAllByText("Operational handoff created")).toHaveLength(2);
    expect(screen.getByText("Cessna Citation · EI-1 · LIGHT_JET")).toBeTruthy();
    expect(
      screen.queryByText(/customer|payment|refund|crew assigned/i),
    ).toBeNull();
  });

  it("binds pages to request generation and paginates without per-card detail reads", async () => {
    const first = Array.from({ length: 20 }, (_, index) =>
      item(String(index % 10)),
    );
    let resolvePage!: (value: readonly OperatorFlightOperation[]) => void;
    listOperations
      .mockResolvedValueOnce(first)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolvePage = resolve;
          }),
      )
      .mockResolvedValueOnce([item("9")]);
    render(<OperatorOperations organizations={[organizations[0]]} />);
    await screen.findByText("Page 1");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() =>
      expect(listOperations).toHaveBeenLastCalledWith(
        "org-a",
        { limit: 20, offset: 20 },
        expect.any(AbortSignal),
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText("SBJ-9")).toBeTruthy();
    await act(async () => resolvePage([item("8")]));
    expect(screen.queryByText("SBJ-8")).toBeNull();
    expect(getOperation).not.toHaveBeenCalled();
  });

  it("prevents stale A→B→A responses and clears old organization facts", async () => {
    const pending: Array<(value: readonly OperatorFlightOperation[]) => void> =
      [];
    listOperations.mockImplementation(
      () => new Promise((resolve) => pending.push(resolve)),
    );
    render(<OperatorOperations organizations={organizations} />);
    const select = screen.getByLabelText(/Operator organization/);
    fireEvent.change(select, { target: { value: "org-a" } });
    await waitFor(() => expect(listOperations).toHaveBeenCalledTimes(1));
    fireEvent.change(select, { target: { value: "org-b" } });
    await waitFor(() => expect(listOperations).toHaveBeenCalledTimes(2));
    fireEvent.change(select, { target: { value: "org-a" } });
    await waitFor(() => expect(listOperations).toHaveBeenCalledTimes(3));
    await act(async () => pending[2]([item("3")]));
    expect(await screen.findByText("SBJ-3")).toBeTruthy();
    await act(async () => {
      pending[0]([item("1")]);
      pending[1]([item("2")]);
    });
    expect(screen.queryByText("SBJ-1")).toBeNull();
    expect(screen.queryByText("SBJ-2")).toBeNull();
  });

  it("prevents stale detail facts across rapid A→B→A→B switches", async () => {
    const pending: Array<(value: OperatorFlightOperation) => void> = [];
    getOperation.mockImplementation(
      () => new Promise((resolve) => pending.push(resolve)),
    );
    render(
      <OperatorOperations
        organizations={organizations}
        operationId={item("6").operation_id}
      />,
    );
    const select = screen.getByLabelText(/Operator organization/);
    for (const organizationId of ["org-a", "org-b", "org-a", "org-b"]) {
      fireEvent.change(select, { target: { value: organizationId } });
      await waitFor(() =>
        expect(getOperation).toHaveBeenCalledTimes(pending.length),
      );
    }
    await act(async () => pending[3](item("4")));
    expect(await screen.findByText("SBJ-4")).toBeTruthy();
    await act(async () => {
      pending[0](item("1"));
      pending[1](item("2"));
      pending[2](item("3"));
    });
    expect(screen.queryByText("SBJ-1")).toBeNull();
    expect(screen.queryByText("SBJ-2")).toBeNull();
    expect(screen.queryByText("SBJ-3")).toBeNull();
  });

  it("steps back exactly one bounded page when the next page is empty", async () => {
    const first = Array.from({ length: 20 }, (_, index) =>
      item(String(index % 10)),
    );
    listOperations
      .mockResolvedValueOnce(first)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce(first);
    render(<OperatorOperations organizations={[organizations[0]]} />);
    await screen.findByText("Page 1");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() =>
      expect(listOperations).toHaveBeenCalledWith(
        "org-a",
        { limit: 20, offset: 20 },
        expect.any(AbortSignal),
      ),
    );
    expect(await screen.findByText("Page 1")).toBeTruthy();
    await waitFor(() => expect(listOperations).toHaveBeenCalledTimes(3));
    expect(listOperations).toHaveBeenLastCalledWith(
      "org-a",
      { limit: 20, offset: 0 },
      expect.any(AbortSignal),
    );
    expect(getOperation).not.toHaveBeenCalled();
  });

  it("renders cancelled Booking separately and unknown operation status fail-closed", async () => {
    const unknown = {
      ...item("4", "CANCELLED"),
      status: "FUTURE" as "HANDOFF_CREATED",
    };
    getOperation.mockResolvedValue(unknown);
    render(
      <OperatorOperations
        organizations={[organizations[0]]}
        operationId={unknown.operation_id}
      />,
    );
    expect(
      await screen.findAllByText("Operational status unavailable"),
    ).toHaveLength(2);
    expect(screen.getByText(/Booking status: Cancelled/)).toBeTruthy();
    expect(screen.getByText(/retained for history/)).toBeTruthy();
    expect(
      screen.queryByRole("button", {
        name: /dispatch|complete|cancel operation/i,
      }),
    ).toBeNull();
  });

  it("isolates not-found and read failures from empty state", async () => {
    getOperation.mockRejectedValue(
      new ApiError(404, "not_found", "hidden", "client"),
    );
    const { unmount } = render(
      <OperatorOperations
        organizations={[organizations[0]]}
        operationId={item("5").operation_id}
      />,
    );
    expect(await screen.findByText("Operation not found")).toBeTruthy();
    unmount();
    listOperations.mockRejectedValue(
      new ApiError(500, "server", "raw secret", "server"),
    );
    render(<OperatorOperations organizations={[organizations[0]]} />);
    expect(
      await screen.findByText("Operations could not be loaded"),
    ).toBeTruthy();
    expect(screen.queryByText("raw secret")).toBeNull();
    expect(screen.queryByText("No operational handoffs")).toBeNull();
  });
});
