import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OperatorOpportunityMarketplace } from "@/components/operator/OperatorOpportunityMarketplace";
import { ApiError } from "@/lib/api/errors";
import type { OperatorOffer, OperatorOpportunity } from "@/lib/api/types";

const api = vi.hoisted(() => ({
  listOperatorOpportunities: vi.fn(),
  listOperatorAircraft: vi.fn(),
  createOperatorOffer: vi.fn(),
  getOperatorOffer: vi.fn(),
  updateOperatorOffer: vi.fn(),
  submitOperatorOffer: vi.fn(),
  withdrawOperatorOffer: vi.fn(),
}));
vi.mock("@/lib/api/client", () => ({ portalApi: api }));

const opportunity = {
  trip_request_id: "trip-1",
  status: "SUBMITTED",
  created_at: "2026-08-27T00:00:00Z",
  own_offers: [],
  legs: [
    {
      sequence: 1,
      origin_airport_code: "EIDW",
      destination_airport_code: "EGLF",
      departure_at: "2026-12-01T14:00:00Z",
      passenger_count: 3,
    },
  ],
} as const;
const aircraft = {
  id: "aircraft-1",
  registration: "EI-SBJ",
  manufacturer: "Cessna",
  model: "Citation",
  category: "LIGHT_JET",
  passenger_capacity: 7,
  status: "ACTIVE",
  eligible: true,
} as const;
const admin = [{ id: "org-1", role: "OPERATOR_ADMIN", canManage: true }];
const multiOrg = [
  { id: "org-a", role: "OPERATOR_ADMIN", canManage: true },
  { id: "org-b", role: "OPERATOR_SALES", canManage: true },
];
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}
const offerResponse = {
  id: "offer-1",
  trip_request_id: "trip-1",
  aircraft_id: "aircraft-1",
  status: "DRAFT",
  currency: "EUR",
  operator_amount_minor: 12345,
  tax_amount_minor: 100,
  valid_until: null,
  aircraft_registration: "EI-SBJ",
  aircraft_manufacturer: "Cessna",
  aircraft_model: "Citation",
  aircraft_category: "LIGHT_JET",
  operator_notes: null,
  cancellation_policy: null,
  included_services: null,
  excluded_services: null,
  created_at: "2026-08-27T00:00:00Z",
  updated_at: "2026-08-27T00:00:00Z",
} as const;

beforeEach(() => {
  Object.values(api).forEach((mock) => mock.mockReset());
  api.listOperatorOpportunities.mockResolvedValue([opportunity]);
  api.listOperatorAircraft.mockResolvedValue([aircraft]);
});

describe("OperatorOpportunityMarketplace", () => {
  it("renders only factual opportunity fields and read-only roles have no mutations", async () => {
    render(
      <OperatorOpportunityMarketplace
        organizations={[
          { id: "org-1", role: "OPERATOR_OPERATIONS", canManage: false },
        ]}
      />,
    );
    expect(await screen.findByText(/EIDW/)).toBeTruthy();
    expect(screen.getByText("3 passengers")).toBeTruthy();
    expect(screen.getByText("Read-only access")).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: /create|submit|withdraw|save/i }),
    ).toBeNull();
    expect(document.body.textContent).not.toMatch(
      /customer|passenger name|platform fee|payment/i,
    );
  });

  it("creates a DRAFT with integer minor units and server-derived operator", async () => {
    api.createOperatorOffer.mockResolvedValue(offerResponse);
    render(<OperatorOpportunityMarketplace organizations={admin} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Create offer" }),
    );
    fireEvent.change(screen.getByRole("combobox", { name: "Aircraft" }), {
      target: { value: "aircraft-1" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Operator amount" }), {
      target: { value: "123.45" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Tax amount" }), {
      target: { value: "1.00" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() =>
      expect(api.createOperatorOffer).toHaveBeenCalledTimes(1),
    );
    expect(api.createOperatorOffer.mock.calls[0][0]).toMatchObject({
      trip_request_id: "trip-1",
      aircraft_id: "aircraft-1",
      operator_amount_minor: 12345,
      tax_amount_minor: 100,
    });
    expect(
      JSON.stringify(api.createOperatorOffer.mock.calls[0][0]),
    ).not.toContain("operator_id");
  });

  it("loads no per-card offer details and requires explicit org selection", async () => {
    render(
      <OperatorOpportunityMarketplace
        organizations={[
          { id: "org-a", role: "OPERATOR_ADMIN", canManage: true },
          { id: "org-b", role: "OPERATOR_SALES", canManage: true },
        ]}
      />,
    );
    expect(
      screen.getByText("Choose operator organization", {
        selector: ".state__title",
      }),
    ).toBeTruthy();
    expect(api.listOperatorOpportunities).not.toHaveBeenCalled();
    fireEvent.change(
      screen.getByRole("combobox", { name: "Operator organization" }),
      { target: { value: "org-b" } },
    );
    expect(await screen.findByText(/EIDW/)).toBeTruthy();
    expect(api.getOperatorOffer).not.toHaveBeenCalled();
    expect(api.listOperatorOpportunities).toHaveBeenCalledWith(
      "org-b",
      expect.any(AbortSignal),
    );
  });

  it.each(["OPERATOR_OPERATIONS", "OPERATOR_FINANCE", "OPERATOR_COMPLIANCE"])(
    "keeps %s strictly read-only",
    async (role) => {
      render(
        <OperatorOpportunityMarketplace
          organizations={[{ id: "org-1", role, canManage: false }]}
        />,
      );
      await screen.findByText(/EIDW/);
      expect(
        screen.queryByRole("button", {
          name: /create|edit|submit|withdraw|save/i,
        }),
      ).toBeNull();
    },
  );

  it.each(["OPERATOR_ADMIN", "OPERATOR_SALES"])(
    "allows canonical create controls for %s",
    async (role) => {
      render(
        <OperatorOpportunityMarketplace
          organizations={[{ id: "org-1", role, canManage: true }]}
        />,
      );
      expect(
        await screen.findByRole("button", { name: "Create offer" }),
      ).toBeTruthy();
    },
  );

  it("renders multiple factual own states without GET-per-card and fails closed for immutable states", async () => {
    api.listOperatorOpportunities.mockResolvedValue([
      {
        ...opportunity,
        own_offers: [
          { offer_id: "draft", status: "DRAFT" },
          { offer_id: "submitted", status: "SUBMITTED" },
          { offer_id: "selected", status: "SELECTED" },
          { offer_id: "withdrawn", status: "WITHDRAWN" },
          { offer_id: "expired", status: "EXPIRED" },
          { offer_id: "future", status: "FUTURE" },
        ],
      },
    ]);
    render(<OperatorOpportunityMarketplace organizations={admin} />);
    await screen.findByText("DRAFT");
    for (const status of [
      "SUBMITTED",
      "SELECTED",
      "WITHDRAWN",
      "EXPIRED",
      "FUTURE",
    ])
      expect(screen.getByText(status)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Edit draft" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Submit offer" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Withdraw offer" })).toBeTruthy();
    expect(api.getOperatorOffer).not.toHaveBeenCalled();
  });

  it("guards a double submit synchronously", async () => {
    api.listOperatorOpportunities.mockResolvedValue([
      { ...opportunity, own_offers: [{ offer_id: "draft", status: "DRAFT" }] },
    ]);
    let resolve!: (value: unknown) => void;
    api.submitOperatorOffer.mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    render(<OperatorOpportunityMarketplace organizations={admin} />);
    const submit = await screen.findByRole("button", { name: "Submit offer" });
    fireEvent.click(submit);
    fireEvent.click(submit);
    expect(api.submitOperatorOffer).toHaveBeenCalledTimes(1);
    resolve({ ...offerResponse, status: "SUBMITTED" });
  });

  it("performs one authoritative GET after 409 and never retries the mutation", async () => {
    api.listOperatorOpportunities.mockResolvedValue([
      {
        ...opportunity,
        own_offers: [{ offer_id: "submitted", status: "SUBMITTED" }],
      },
    ]);
    api.withdrawOperatorOffer.mockRejectedValue(
      new ApiError(409, "conflict", "raw backend detail", "conflict"),
    );
    api.getOperatorOffer.mockResolvedValue({
      ...offerResponse,
      id: "submitted",
      status: "WITHDRAWN",
    });
    render(<OperatorOpportunityMarketplace organizations={admin} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Withdraw offer" }),
    );
    expect(
      await screen.findByText(/authoritative state was refreshed/i),
    ).toBeTruthy();
    expect(api.withdrawOperatorOffer).toHaveBeenCalledTimes(1);
    expect(api.getOperatorOffer).toHaveBeenCalledTimes(1);
    expect(document.body.textContent).not.toContain("raw backend detail");
  });

  it("discards a delayed Org A detail response after switching to Org B", async () => {
    let resolveDetail!: (value: unknown) => void;
    api.listOperatorOpportunities.mockImplementation((orgId: string) =>
      Promise.resolve([
        {
          ...opportunity,
          own_offers:
            orgId === "org-a" ? [{ offer_id: "offer-a", status: "DRAFT" }] : [],
        },
      ]),
    );
    api.getOperatorOffer.mockImplementation(
      () => new Promise((resolve) => (resolveDetail = resolve)),
    );
    render(<OperatorOpportunityMarketplace organizations={multiOrg} />);
    const chooser = screen.getByRole("combobox", {
      name: "Operator organization",
    });
    fireEvent.change(chooser, { target: { value: "org-a" } });
    fireEvent.click(await screen.findByRole("button", { name: "Edit draft" }));
    fireEvent.change(chooser, { target: { value: "org-b" } });
    await screen.findByText("No offer created.");
    resolveDetail({
      ...offerResponse,
      id: "offer-a",
      aircraft_registration: "A-PRIVATE",
    });
    await waitFor(() => expect(api.getOperatorOffer).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "Edit draft offer" }),
      ).toBeNull(),
    );
    expect(document.body.textContent).not.toContain("A-PRIVATE");
    expect(screen.queryByText("DRAFT", { exact: true })).toBeNull();
  });

  it("does not let a late Org A finally release Org B's mutation token", async () => {
    let resolveA!: (value: unknown) => void;
    let resolveB!: (value: unknown) => void;
    api.listOperatorOpportunities.mockImplementation((orgId: string) =>
      Promise.resolve([
        {
          ...opportunity,
          own_offers: [
            {
              offer_id: orgId === "org-a" ? "offer-a" : "offer-b",
              status: "SUBMITTED",
            },
          ],
        },
      ]),
    );
    api.withdrawOperatorOffer.mockImplementation(
      (offerId: string) =>
        new Promise((resolve) => {
          if (offerId === "offer-a") resolveA = resolve;
          else resolveB = resolve;
        }),
    );
    render(<OperatorOpportunityMarketplace organizations={multiOrg} />);
    const chooser = screen.getByRole("combobox", {
      name: "Operator organization",
    });
    fireEvent.change(chooser, { target: { value: "org-a" } });
    fireEvent.click(
      await screen.findByRole("button", { name: "Withdraw offer" }),
    );
    fireEvent.change(chooser, { target: { value: "org-b" } });
    const withdrawB = await screen.findByRole("button", {
      name: "Withdraw offer",
    });
    fireEvent.click(withdrawB);
    expect(api.withdrawOperatorOffer).toHaveBeenCalledTimes(2);
    resolveA({ ...offerResponse, id: "offer-a", status: "WITHDRAWN" });
    await waitFor(() =>
      expect((withdrawB as HTMLButtonElement).disabled).toBe(true),
    );
    fireEvent.click(withdrawB);
    expect(api.withdrawOperatorOffer).toHaveBeenCalledTimes(2);
    resolveB({ ...offerResponse, id: "offer-b", status: "WITHDRAWN" });
  });

  it.each(["create", "edit", "submit", "withdraw"] as const)(
    "discards delayed Org A %s success after switching to Org B",
    async (action) => {
      const late = deferred<OperatorOffer>();
      api.listOperatorOpportunities.mockImplementation((orgId: string) =>
        Promise.resolve([
          {
            ...opportunity,
            own_offers:
              orgId === "org-b" || action === "create"
                ? []
                : [
                    {
                      offer_id: "offer-a",
                      status: action === "withdraw" ? "SUBMITTED" : "DRAFT",
                    },
                  ],
          },
        ]),
      );
      api.getOperatorOffer.mockResolvedValue({
        ...offerResponse,
        id: "offer-a",
      });
      if (action === "create")
        api.createOperatorOffer.mockReturnValue(late.promise);
      if (action === "edit")
        api.updateOperatorOffer.mockReturnValue(late.promise);
      if (action === "submit")
        api.submitOperatorOffer.mockReturnValue(late.promise);
      if (action === "withdraw")
        api.withdrawOperatorOffer.mockReturnValue(late.promise);
      render(<OperatorOpportunityMarketplace organizations={multiOrg} />);
      const chooser = screen.getByRole("combobox", {
        name: "Operator organization",
      });
      fireEvent.change(chooser, { target: { value: "org-a" } });
      if (action === "create") {
        fireEvent.click(
          await screen.findByRole("button", { name: "Create offer" }),
        );
        fireEvent.change(screen.getByRole("combobox", { name: "Aircraft" }), {
          target: { value: "aircraft-1" },
        });
        fireEvent.change(
          screen.getByRole("textbox", { name: "Operator amount" }),
          { target: { value: "10.00" } },
        );
        fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
      } else if (action === "edit") {
        fireEvent.click(
          await screen.findByRole("button", { name: "Edit draft" }),
        );
        await screen.findByRole("heading", { name: "Edit draft offer" });
        fireEvent.change(
          screen.getByRole("textbox", { name: "Operator amount" }),
          { target: { value: "20.00" } },
        );
        fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
      } else {
        fireEvent.click(
          await screen.findByRole("button", {
            name: action === "submit" ? "Submit offer" : "Withdraw offer",
          }),
        );
      }
      fireEvent.change(chooser, { target: { value: "org-b" } });
      await screen.findByText("No offer created.");
      late.resolve({
        ...offerResponse,
        id: "offer-a-private",
        status: action === "withdraw" ? "WITHDRAWN" : "DRAFT",
        aircraft_registration: "A-PRIVATE",
      });
      await waitFor(() =>
        expect(document.body.textContent).not.toContain("A-PRIVATE"),
      );
      expect(document.body.textContent).not.toContain("offer-a-private");
      expect(screen.queryByText("DRAFT", { exact: true })).toBeNull();
      expect(
        screen.queryByRole("heading", { name: /draft offer/i }),
      ).toBeNull();
    },
  );

  it.each([
    new ApiError(403, "forbidden", "A forbidden", "forbidden"),
    new ApiError(404, "missing", "A missing", "client"),
    new ApiError(0, "network", "A network", "network"),
  ])(
    "discards a delayed Org A failure after switching to Org B",
    async (failure) => {
      const late = deferred<never>();
      api.listOperatorOpportunities.mockImplementation((orgId: string) =>
        Promise.resolve([
          {
            ...opportunity,
            own_offers:
              orgId === "org-a"
                ? [{ offer_id: "offer-a", status: "SUBMITTED" }]
                : [],
          },
        ]),
      );
      api.withdrawOperatorOffer.mockReturnValue(late.promise);
      render(<OperatorOpportunityMarketplace organizations={multiOrg} />);
      const chooser = screen.getByRole("combobox", {
        name: "Operator organization",
      });
      fireEvent.change(chooser, { target: { value: "org-a" } });
      fireEvent.click(
        await screen.findByRole("button", { name: "Withdraw offer" }),
      );
      fireEvent.change(chooser, { target: { value: "org-b" } });
      await screen.findByText("No offer created.");
      late.reject(failure);
      await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
      expect(document.body.textContent).not.toContain(failure.message);
    },
  );

  it("does not start a conflict refresh for a stale Org A 409", async () => {
    const late = deferred<never>();
    api.listOperatorOpportunities.mockImplementation((orgId: string) =>
      Promise.resolve([
        {
          ...opportunity,
          own_offers:
            orgId === "org-a"
              ? [{ offer_id: "offer-a", status: "SUBMITTED" }]
              : [],
        },
      ]),
    );
    api.withdrawOperatorOffer.mockReturnValue(late.promise);
    render(<OperatorOpportunityMarketplace organizations={multiOrg} />);
    const chooser = screen.getByRole("combobox", {
      name: "Operator organization",
    });
    fireEvent.change(chooser, { target: { value: "org-a" } });
    fireEvent.click(
      await screen.findByRole("button", { name: "Withdraw offer" }),
    );
    fireEvent.change(chooser, { target: { value: "org-b" } });
    await screen.findByText("No offer created.");
    late.reject(new ApiError(409, "conflict", "A conflict", "conflict"));
    await waitFor(() => expect(api.getOperatorOffer).not.toHaveBeenCalled());
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("rejects an old A epoch after A to B to A", async () => {
    const oldA = deferred<OperatorOffer>();
    api.listOperatorOpportunities.mockImplementation((orgId: string) =>
      Promise.resolve([
        {
          ...opportunity,
          own_offers:
            orgId === "org-a" ? [{ offer_id: "offer-a", status: "DRAFT" }] : [],
        },
      ]),
    );
    api.getOperatorOffer.mockReturnValue(oldA.promise);
    render(<OperatorOpportunityMarketplace organizations={multiOrg} />);
    const chooser = screen.getByRole("combobox", {
      name: "Operator organization",
    });
    fireEvent.change(chooser, { target: { value: "org-a" } });
    fireEvent.click(await screen.findByRole("button", { name: "Edit draft" }));
    fireEvent.change(chooser, { target: { value: "org-b" } });
    await screen.findByText("No offer created.");
    fireEvent.change(chooser, { target: { value: "org-a" } });
    await screen.findByRole("button", { name: "Edit draft" });
    oldA.resolve({ ...offerResponse, aircraft_registration: "OLD-A" });
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "Edit draft offer" }),
      ).toBeNull(),
    );
    expect(document.body.textContent).not.toContain("OLD-A");
  });

  it("accepts only the latest epoch across rapid switches even when reads ignore abort", async () => {
    const reads = [
      deferred<readonly OperatorOpportunity[]>(),
      deferred<readonly OperatorOpportunity[]>(),
      deferred<readonly OperatorOpportunity[]>(),
      deferred<readonly OperatorOpportunity[]>(),
    ];
    let call = 0;
    api.listOperatorOpportunities.mockImplementation(
      () => reads[call++].promise,
    );
    render(<OperatorOpportunityMarketplace organizations={multiOrg} />);
    const chooser = screen.getByRole("combobox", {
      name: "Operator organization",
    });
    for (const [index, orgId] of [
      "org-a",
      "org-b",
      "org-a",
      "org-b",
    ].entries()) {
      fireEvent.change(chooser, { target: { value: orgId } });
      await waitFor(() =>
        expect(api.listOperatorOpportunities).toHaveBeenCalledTimes(index + 1),
      );
    }
    const withOrigin = (origin: string): OperatorOpportunity => ({
      ...opportunity,
      legs: [{ ...opportunity.legs[0], origin_airport_code: origin }],
    });
    reads[3].resolve([withOrigin("LATEST")]);
    await screen.findByText(/LATEST/);
    reads[2].resolve([withOrigin("OLD-A-2")]);
    reads[1].resolve([withOrigin("OLD-B-1")]);
    reads[0].resolve([withOrigin("OLD-A-1")]);
    await waitFor(() => expect(document.body.textContent).toContain("LATEST"));
    expect(document.body.textContent).not.toMatch(/OLD-A|OLD-B/);
  });
});
