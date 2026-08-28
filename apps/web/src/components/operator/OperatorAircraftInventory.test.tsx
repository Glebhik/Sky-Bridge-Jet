import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OperatorAircraftInventory } from "./OperatorAircraftInventory";

const api = vi.hoisted(() => ({
  listOperatorAircraftPage: vi.fn(),
  createOperatorAircraft: vi.fn(),
}));
vi.mock("@/lib/api/client", () => ({ portalApi: api }));
const aircraft = {
  id: "11111111-2222-4333-8444-555555555555",
  registration: "EI-SBJ",
  manufacturer: "Cessna",
  model: "Citation",
  category: "LIGHT_JET",
  passenger_capacity: 7,
  status: "ACTIVE",
  eligible: true,
};
const admin = [{ id: "org-a", role: "OPERATOR_ADMIN", canCreate: true }];

describe("OperatorAircraftInventory", () => {
  beforeEach(() => {
    api.listOperatorAircraftPage.mockReset().mockResolvedValue([aircraft]);
    api.createOperatorAircraft.mockReset().mockResolvedValue(aircraft);
  });
  it("loads one bounded collection and renders only factual fields", async () => {
    render(<OperatorAircraftInventory organizations={admin} />);
    expect(await screen.findByText("EI-SBJ")).toBeInTheDocument();
    expect(api.listOperatorAircraftPage).toHaveBeenCalledTimes(1);
    expect(
      screen.getByText("Eligible for marketplace offers"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/certified|airworthy|guaranteed/i),
    ).not.toBeInTheDocument();
  });
  it("does not request data before an explicit multi-org selection", async () => {
    render(
      <OperatorAircraftInventory
        organizations={[
          ...admin,
          { id: "org-b", role: "OPERATOR_USER", canCreate: false },
        ]}
      />,
    );
    expect(screen.getAllByText("Choose operator organization")).toHaveLength(2);
    expect(api.listOperatorAircraftPage).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Operator organization"), {
      target: { value: "org-b" },
    });
    await waitFor(() =>
      expect(api.listOperatorAircraftPage).toHaveBeenCalledWith(
        "org-b",
        { limit: 20, offset: 0 },
        expect.any(AbortSignal),
      ),
    );
  });
  it("omits create authority for every non-admin role", async () => {
    for (const role of [
      "OPERATOR_OPERATIONS",
      "OPERATOR_FINANCE",
      "OPERATOR_SALES",
      "OPERATOR_COMPLIANCE",
    ]) {
      const view = render(
        <OperatorAircraftInventory
          organizations={[{ id: role, role, canCreate: false }]}
        />,
      );
      await screen.findByText("EI-SBJ");
      expect(
        screen.queryByRole("button", { name: "Add aircraft" }),
      ).not.toBeInTheDocument();
      view.unmount();
    }
  });
  it("creates once with the exact safe payload and authoritative response", async () => {
    api.listOperatorAircraftPage.mockResolvedValue([]);
    render(<OperatorAircraftInventory organizations={admin} />);
    await screen.findByText("No aircraft found");
    fireEvent.change(screen.getByLabelText("Registration"), {
      target: { value: "EI-SBJ" },
    });
    fireEvent.change(screen.getByLabelText("Manufacturer"), {
      target: { value: "Cessna" },
    });
    fireEvent.change(screen.getByLabelText("Model"), {
      target: { value: "Citation" },
    });
    fireEvent.change(screen.getByLabelText("Category"), {
      target: { value: "LIGHT_JET" },
    });
    fireEvent.change(screen.getByLabelText("Passenger capacity"), {
      target: { value: "7" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add aircraft" }));
    await waitFor(() =>
      expect(api.createOperatorAircraft).toHaveBeenCalledTimes(1),
    );
    expect(api.createOperatorAircraft).toHaveBeenCalledWith(
      {
        registration: "EI-SBJ",
        manufacturer: "Cessna",
        model: "Citation",
        category: "LIGHT_JET",
        passenger_capacity: 7,
      },
      "org-a",
    );
  });
  it("isolates read errors and retries only on manual refresh", async () => {
    api.listOperatorAircraftPage
      .mockRejectedValueOnce(new Error("down"))
      .mockResolvedValueOnce([]);
    render(<OperatorAircraftInventory organizations={admin} />);
    expect(
      await screen.findByText("Aircraft could not be loaded"),
    ).toBeInTheDocument();
    expect(api.listOperatorAircraftPage).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Refresh aircraft" }));
    await waitFor(() =>
      expect(api.listOperatorAircraftPage).toHaveBeenCalledTimes(2),
    );
  });

  it("discards a late create result after an A to B organization switch", async () => {
    api.listOperatorAircraftPage.mockResolvedValue([]);
    let resolveA!: (value: typeof aircraft) => void;
    api.createOperatorAircraft.mockImplementation(
      (_body: unknown, org: string) =>
        org === "org-a"
          ? new Promise((resolve) => {
              resolveA = resolve;
            })
          : Promise.resolve({ ...aircraft, registration: "EI-BBB" }),
    );
    render(
      <OperatorAircraftInventory
        organizations={[admin[0], { ...admin[0], id: "org-b" }]}
      />,
    );
    const select = screen.getByLabelText("Operator organization");
    fireEvent.change(select, { target: { value: "org-a" } });
    await screen.findByText("No aircraft found");
    for (const [label, value] of [
      ["Registration", "EI-AAA"],
      ["Manufacturer", "Cessna"],
      ["Model", "Citation"],
      ["Category", "LIGHT_JET"],
      ["Passenger capacity", "7"],
    ])
      fireEvent.change(screen.getByLabelText(label), { target: { value } });
    fireEvent.click(screen.getByRole("button", { name: "Add aircraft" }));
    await waitFor(() =>
      expect(api.createOperatorAircraft).toHaveBeenCalledTimes(1),
    );
    fireEvent.change(select, { target: { value: "org-b" } });
    await screen.findByText("No aircraft found");
    for (const [label, value] of [
      ["Registration", "EI-BBB"],
      ["Manufacturer", "Cessna"],
      ["Model", "Citation"],
      ["Category", "LIGHT_JET"],
      ["Passenger capacity", "7"],
    ])
      fireEvent.change(screen.getByLabelText(label), { target: { value } });
    fireEvent.click(screen.getByRole("button", { name: "Add aircraft" }));
    await waitFor(() =>
      expect(api.createOperatorAircraft).toHaveBeenCalledTimes(2),
    );
    resolveA({ ...aircraft, registration: "EI-AAA" });
    await Promise.resolve();
    expect(screen.queryByText("EI-AAA")).not.toBeInTheDocument();
  });

  it("offers bounded server continuation when a fleet exceeds one page", async () => {
    const fleet = Array.from({ length: 101 }, (_, index) => ({
      ...aircraft,
      id: `11111111-2222-4333-8444-${String(index).padStart(12, "0")}`,
      registration: `EI-${String(index).padStart(3, "0")}`,
    }));
    api.listOperatorAircraftPage.mockImplementation(
      (_org: string, query: { limit: number; offset: number }) =>
        Promise.resolve(fleet.slice(query.offset, query.offset + query.limit)),
    );
    render(<OperatorAircraftInventory organizations={admin} />);
    expect(await screen.findByText("EI-000")).toBeInTheDocument();
    expect(screen.queryByText("EI-020")).not.toBeInTheDocument();
    for (let page = 2; page <= 6; page += 1) {
      fireEvent.click(screen.getByRole("button", { name: "Next" }));
      await screen.findByText(`Page ${page} · up to 20 aircraft on this page`);
    }
    expect(await screen.findByText("EI-100")).toBeInTheDocument();
    expect(api.listOperatorAircraftPage).toHaveBeenLastCalledWith(
      "org-a",
      { limit: 20, offset: 100 },
      expect.any(AbortSignal),
    );
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(await screen.findByText("EI-080")).toBeInTheDocument();
  });

  it("allows a new A epoch create while the old A epoch is still pending", async () => {
    api.listOperatorAircraftPage.mockResolvedValue([]);
    const pending: Array<(value: typeof aircraft) => void> = [];
    api.createOperatorAircraft.mockImplementation(
      () => new Promise((resolve) => pending.push(resolve)),
    );
    render(
      <OperatorAircraftInventory
        organizations={[admin[0], { ...admin[0], id: "org-b" }]}
      />,
    );
    const select = screen.getByLabelText("Operator organization");
    const fill = (registration: string) => {
      for (const [label, value] of [
        ["Registration", registration],
        ["Manufacturer", "Cessna"],
        ["Model", "Citation"],
        ["Category", "LIGHT_JET"],
        ["Passenger capacity", "7"],
      ])
        fireEvent.change(screen.getByLabelText(label), { target: { value } });
    };
    fireEvent.change(select, { target: { value: "org-a" } });
    await screen.findByText("No aircraft found");
    fill("EI-A1");
    fireEvent.click(screen.getByRole("button", { name: "Add aircraft" }));
    await waitFor(() =>
      expect(api.createOperatorAircraft).toHaveBeenCalledTimes(1),
    );
    fireEvent.change(select, { target: { value: "org-b" } });
    await screen.findByText("No aircraft found");
    fireEvent.change(select, { target: { value: "org-a" } });
    await screen.findByText("No aircraft found");
    fill("EI-A3");
    fireEvent.click(screen.getByRole("button", { name: "Add aircraft" }));
    await waitFor(() =>
      expect(api.createOperatorAircraft).toHaveBeenCalledTimes(2),
    );
    expect(pending).toHaveLength(2);
  });

  it("keeps a newer page when an older page resolves late", async () => {
    const page = (prefix: string) =>
      Array.from({ length: 20 }, (_, index) => ({
        ...aircraft,
        id: `${prefix}-${index}`,
        registration: `${prefix}-${index}`,
      }));
    let resolveNext!: (value: readonly (typeof aircraft)[]) => void;
    api.listOperatorAircraftPage
      .mockResolvedValueOnce(page("P1"))
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveNext = resolve;
          }),
      )
      .mockResolvedValueOnce(page("P1-new"));
    render(<OperatorAircraftInventory organizations={admin} />);
    await screen.findByText("P1-0");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(await screen.findByText("P1-new-0")).toBeInTheDocument();
    resolveNext(page("P2-late"));
    await Promise.resolve();
    expect(screen.queryByText("P2-late-0")).not.toBeInTheDocument();
  });

  it("prevents an old finally from releasing the newer A epoch token", async () => {
    api.listOperatorAircraftPage.mockResolvedValue([]);
    const attempts: Array<{
      resolve: (value: typeof aircraft) => void;
    }> = [];
    api.createOperatorAircraft.mockImplementation(
      () => new Promise((resolve) => attempts.push({ resolve })),
    );
    render(
      <OperatorAircraftInventory
        organizations={[admin[0], { ...admin[0], id: "org-b" }]}
      />,
    );
    const select = screen.getByLabelText("Operator organization");
    const submit = (registration: string) => {
      for (const [label, value] of [
        ["Registration", registration],
        ["Manufacturer", "Cessna"],
        ["Model", "Citation"],
        ["Category", "LIGHT_JET"],
        ["Passenger capacity", "7"],
      ])
        fireEvent.change(screen.getByLabelText(label), { target: { value } });
      fireEvent.submit(
        screen
          .getByRole("button", { name: /Add aircraft|Adding aircraft/ })
          .closest("form")!,
      );
    };
    fireEvent.change(select, { target: { value: "org-a" } });
    await screen.findByText("No aircraft found");
    submit("EI-A1");
    await waitFor(() => expect(attempts).toHaveLength(1));
    fireEvent.change(select, { target: { value: "org-b" } });
    await screen.findByText("No aircraft found");
    fireEvent.change(select, { target: { value: "org-a" } });
    await screen.findByText("No aircraft found");
    submit("EI-A3");
    await waitFor(() => expect(attempts).toHaveLength(2));
    attempts[0].resolve({ ...aircraft, registration: "EI-A1" });
    await Promise.resolve();
    fireEvent.submit(
      screen.getByRole("button", { name: "Adding aircraft…" }).closest("form")!,
    );
    expect(api.createOperatorAircraft).toHaveBeenCalledTimes(2);
    attempts[1].resolve({ ...aircraft, registration: "EI-A3" });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Add aircraft" }),
      ).toBeEnabled(),
    );
  });

  it("issues one POST for same-epoch duplicate submission", async () => {
    api.listOperatorAircraftPage.mockResolvedValue([]);
    api.createOperatorAircraft.mockReturnValue(new Promise(() => undefined));
    render(<OperatorAircraftInventory organizations={admin} />);
    await screen.findByText("No aircraft found");
    for (const [label, value] of [
      ["Registration", "EI-ONE"],
      ["Manufacturer", "Cessna"],
      ["Model", "Citation"],
      ["Category", "LIGHT_JET"],
      ["Passenger capacity", "7"],
    ])
      fireEvent.change(screen.getByLabelText(label), { target: { value } });
    const form = screen
      .getByRole("button", { name: "Add aircraft" })
      .closest("form")!;
    fireEvent.submit(form);
    fireEvent.submit(form);
    expect(api.createOperatorAircraft).toHaveBeenCalledTimes(1);
  });

  it("rejects a late page after an organization switch", async () => {
    const fullPage = Array.from({ length: 20 }, (_, index) => ({
      ...aircraft,
      id: `a-${index}`,
      registration: `A-${index}`,
    }));
    let resolveOldPage!: (value: readonly (typeof aircraft)[]) => void;
    api.listOperatorAircraftPage.mockImplementation(
      (org: string, query: { offset: number }) => {
        if (org === "org-a" && query.offset === 0)
          return Promise.resolve(fullPage);
        if (org === "org-a")
          return new Promise((resolve) => {
            resolveOldPage = resolve;
          });
        return Promise.resolve([
          { ...aircraft, id: "b", registration: "B-ONLY" },
        ]);
      },
    );
    render(
      <OperatorAircraftInventory
        organizations={[admin[0], { ...admin[0], id: "org-b" }]}
      />,
    );
    const select = screen.getByLabelText("Operator organization");
    fireEvent.change(select, { target: { value: "org-a" } });
    await screen.findByText("A-0");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.change(select, { target: { value: "org-b" } });
    expect(await screen.findByText("B-ONLY")).toBeInTheDocument();
    resolveOldPage([{ ...aircraft, registration: "A-LATE" }]);
    await Promise.resolve();
    expect(screen.queryByText("A-LATE")).not.toBeInTheDocument();
  });

  it("keeps stale create errors out of a newer organization epoch", async () => {
    api.listOperatorAircraftPage.mockResolvedValue([]);
    let rejectOld!: (reason: Error) => void;
    api.createOperatorAircraft.mockReturnValueOnce(
      new Promise((_resolve, reject) => {
        rejectOld = reject;
      }),
    );
    render(
      <OperatorAircraftInventory
        organizations={[admin[0], { ...admin[0], id: "org-b" }]}
      />,
    );
    const select = screen.getByLabelText("Operator organization");
    fireEvent.change(select, { target: { value: "org-a" } });
    await screen.findByText("No aircraft found");
    for (const [label, value] of [
      ["Registration", "EI-OLD"],
      ["Manufacturer", "Cessna"],
      ["Model", "Citation"],
      ["Category", "LIGHT_JET"],
      ["Passenger capacity", "7"],
    ])
      fireEvent.change(screen.getByLabelText(label), { target: { value } });
    fireEvent.click(screen.getByRole("button", { name: "Add aircraft" }));
    await waitFor(() =>
      expect(api.createOperatorAircraft).toHaveBeenCalledTimes(1),
    );
    fireEvent.change(select, { target: { value: "org-b" } });
    await screen.findByText("No aircraft found");
    fireEvent.change(select, { target: { value: "org-a" } });
    await screen.findByText("No aircraft found");
    rejectOld(new Error("stale 409"));
    await Promise.resolve();
    expect(screen.queryByText("Aircraft not created")).not.toBeInTheDocument();
  });

  it("resets to the first page with exactly one authoritative refresh after create", async () => {
    const fullPage = Array.from({ length: 20 }, (_, index) => ({
      ...aircraft,
      id: `p-${index}`,
      registration: `P-${index}`,
    }));
    api.listOperatorAircraftPage.mockImplementation(
      (_org: string, query: { offset: number }) =>
        Promise.resolve(
          query.offset === 0
            ? fullPage
            : [{ ...aircraft, registration: "P-20" }],
        ),
    );
    render(<OperatorAircraftInventory organizations={admin} />);
    await screen.findByText("P-0");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("P-20");
    for (const [label, value] of [
      ["Registration", "EI-NEW"],
      ["Manufacturer", "Cessna"],
      ["Model", "Citation"],
      ["Category", "LIGHT_JET"],
      ["Passenger capacity", "7"],
    ])
      fireEvent.change(screen.getByLabelText(label), { target: { value } });
    fireEvent.click(screen.getByRole("button", { name: "Add aircraft" }));
    await screen.findByText("P-0");
    expect(api.listOperatorAircraftPage).toHaveBeenCalledTimes(3);
    expect(api.listOperatorAircraftPage).toHaveBeenLastCalledWith(
      "org-a",
      { limit: 20, offset: 0 },
      expect.any(AbortSignal),
    );
  });
});
