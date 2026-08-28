import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  admissionLabel,
  blockerLabel,
  OperatorComplianceReadinessCenter,
} from "@/components/operator/OperatorComplianceReadinessCenter";

const api = vi.hoisted(() => ({
  getOperatorComplianceReadiness: vi.fn(),
  listOperatorAircraft: vi.fn(),
}));
vi.mock("@/lib/api/client", () => ({ portalApi: api }));

const roles = [
  "OPERATOR_ADMIN",
  "OPERATOR_SALES",
  "OPERATOR_OPERATIONS",
  "OPERATOR_FINANCE",
  "OPERATOR_COMPLIANCE",
] as const;
const readiness = {
  admission_status: "APPROVED",
  marketplace_eligible: true,
  blockers: [],
  created_at: "2026-08-27T10:00:00Z",
  updated_at: "2026-08-27T11:00:00Z",
} as const;
const aircraft = [
  {
    id: "aircraft-1",
    registration: "EI-SBJ",
    manufacturer: "Cessna",
    model: "Citation",
    category: "LIGHT_JET",
    passenger_capacity: 7,
    status: "ACTIVE",
    eligible: true,
  },
  {
    id: "aircraft-2",
    registration: "EI-NOT",
    manufacturer: "Pilatus",
    model: "PC-12",
    category: "TURBOPROP",
    passenger_capacity: 8,
    status: "ACTIVE",
    eligible: false,
  },
] as const;
const oneOrg = [{ id: "org-a", role: "OPERATOR_ADMIN" }];

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  api.getOperatorComplianceReadiness.mockReset().mockResolvedValue(readiness);
  api.listOperatorAircraft.mockReset().mockResolvedValue(aircraft);
});

describe("OperatorComplianceReadinessCenter", () => {
  it.each([
    ["DRAFT", "Draft"],
    ["SUBMITTED", "Submitted"],
    ["UNDER_REVIEW", "Under review"],
    ["APPROVED", "Approved for marketplace admission"],
    ["REJECTED", "Rejected"],
    ["SUSPENDED", "Suspended"],
  ] as const)("maps %s admission factually", (status, label) => {
    expect(admissionLabel(status)).toBe(label);
  });

  it("treats no admission as unknown rather than rejection", async () => {
    api.getOperatorComplianceReadiness.mockResolvedValue({
      ...readiness,
      admission_status: null,
      marketplace_eligible: false,
      blockers: ["OPERATOR_NOT_ADMITTED"],
      created_at: null,
      updated_at: null,
    });
    render(<OperatorComplianceReadinessCenter organizations={oneOrg} />);
    expect(
      await screen.findByText(
        "No operator admission record is currently available.",
      ),
    ).toBeTruthy();
    expect(document.body.textContent).not.toContain("Failed");
  });

  it("renders eligible and ineligible aircraft without inferring reasons", async () => {
    render(<OperatorComplianceReadinessCenter organizations={oneOrg} />);
    expect(await screen.findByText("EI-SBJ")).toBeTruthy();
    expect(screen.getByText("EI-NOT")).toBeTruthy();
    expect(
      screen.getByText("Currently eligible for marketplace offers"),
    ).toBeTruthy();
    expect(screen.getByText("Not currently eligible")).toBeTruthy();
  });

  it("maps multiple blockers and fails closed for a future code", async () => {
    api.getOperatorComplianceReadiness.mockResolvedValue({
      ...readiness,
      marketplace_eligible: false,
      blockers: ["AUTHORITY_EXPIRED", "INSURANCE_NOT_VERIFIED", "FUTURE_CODE"],
    });
    render(<OperatorComplianceReadinessCenter organizations={oneOrg} />);
    expect(
      await screen.findByText("Verified operating authority has expired"),
    ).toBeTruthy();
    expect(screen.getByText("Insurance is not verified")).toBeTruthy();
    expect(screen.getByText("Additional compliance requirement")).toBeTruthy();
    expect(blockerLabel("ANOTHER_FUTURE_CODE")).toBe(
      "Additional compliance requirement",
    );
  });

  it.each(roles)("gives %s the same read-only factual view", async (role) => {
    render(
      <OperatorComplianceReadinessCenter
        organizations={[{ id: "org-a", role }]}
      />,
    );
    expect(
      await screen.findByText("Approved for marketplace admission"),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", {
        name: /submit|upload|approve|reject|suspend/i,
      }),
    ).toBeNull();
  });

  it("requires explicit selection and issues exactly one request pair", async () => {
    render(
      <OperatorComplianceReadinessCenter
        organizations={[
          { id: "org-a", role: "OPERATOR_ADMIN" },
          { id: "org-b", role: "OPERATOR_COMPLIANCE" },
        ]}
      />,
    );
    expect(api.getOperatorComplianceReadiness).not.toHaveBeenCalled();
    expect(api.listOperatorAircraft).not.toHaveBeenCalled();
    fireEvent.change(
      screen.getByRole("combobox", { name: "Operator organization" }),
      {
        target: { value: "org-b" },
      },
    );
    expect(
      await screen.findByText("Approved for marketplace admission"),
    ).toBeTruthy();
    expect(api.getOperatorComplianceReadiness).toHaveBeenCalledTimes(1);
    expect(api.listOperatorAircraft).toHaveBeenCalledTimes(1);
    expect(api.getOperatorComplianceReadiness).toHaveBeenCalledWith(
      "org-b",
      expect.any(AbortSignal),
    );
  });

  it("discards late A in an A to B to A sequence by epoch, not abort alone", async () => {
    const oldAReadiness = deferred<typeof readiness>();
    const oldAAircraft = deferred<typeof aircraft>();
    api.getOperatorComplianceReadiness
      .mockReturnValueOnce(oldAReadiness.promise)
      .mockResolvedValueOnce({ ...readiness, admission_status: "REJECTED" })
      .mockResolvedValueOnce({ ...readiness, admission_status: "SUSPENDED" });
    api.listOperatorAircraft
      .mockReturnValueOnce(oldAAircraft.promise)
      .mockResolvedValueOnce([{ ...aircraft[0], registration: "B-ONLY" }])
      .mockResolvedValueOnce([{ ...aircraft[0], registration: "A-NEW" }]);
    render(
      <OperatorComplianceReadinessCenter
        organizations={[
          { id: "org-a", role: "OPERATOR_ADMIN" },
          { id: "org-b", role: "OPERATOR_ADMIN" },
        ]}
      />,
    );
    const select = screen.getByRole("combobox", {
      name: "Operator organization",
    });
    fireEvent.change(select, { target: { value: "org-a" } });
    await waitFor(() =>
      expect(api.getOperatorComplianceReadiness).toHaveBeenCalledTimes(1),
    );
    fireEvent.change(select, { target: { value: "org-b" } });
    expect(await screen.findByText("Rejected")).toBeTruthy();
    fireEvent.change(select, { target: { value: "org-a" } });
    expect(await screen.findByText("Suspended")).toBeTruthy();
    expect(screen.getByText("A-NEW")).toBeTruthy();
    oldAReadiness.resolve(readiness);
    oldAAircraft.resolve(aircraft);
    await Promise.resolve();
    expect(screen.getByText("Suspended")).toBeTruthy();
    expect(screen.queryByText("EI-NOT")).toBeNull();
  });

  it("isolates readiness and aircraft failures", async () => {
    api.getOperatorComplianceReadiness.mockRejectedValueOnce(
      new Error("readiness"),
    );
    render(<OperatorComplianceReadinessCenter organizations={oneOrg} />);
    expect(
      await screen.findByText("Operator readiness could not be loaded"),
    ).toBeTruthy();
    expect(await screen.findByText("EI-SBJ")).toBeTruthy();

    api.getOperatorComplianceReadiness.mockResolvedValueOnce(readiness);
    api.listOperatorAircraft.mockRejectedValueOnce(new Error("aircraft"));
    fireEvent.click(screen.getByRole("button", { name: "Refresh readiness" }));
    expect(
      await screen.findByText("Aircraft readiness could not be loaded"),
    ).toBeTruthy();
    expect(
      await screen.findByText("Approved for marketplace admission"),
    ).toBeTruthy();
  });

  it("manual refresh issues one new pair and never polls", async () => {
    render(<OperatorComplianceReadinessCenter organizations={oneOrg} />);
    await screen.findByText("EI-SBJ");
    fireEvent.click(screen.getByRole("button", { name: "Refresh readiness" }));
    await waitFor(() =>
      expect(api.listOperatorAircraft).toHaveBeenCalledTimes(2),
    );
    expect(api.getOperatorComplianceReadiness).toHaveBeenCalledTimes(2);
    expect(OperatorComplianceReadinessCenter.toString()).not.toMatch(
      /setInterval|WebSocket|EventSource/,
    );
  });

  it("renders zero-aircraft and safe marketplace boundary states", async () => {
    api.listOperatorAircraft.mockResolvedValue([]);
    render(<OperatorComplianceReadinessCenter organizations={oneOrg} />);
    expect(await screen.findByText("No owned aircraft available")).toBeTruthy();
    expect(
      screen.getByText(/server revalidates every offer command/i),
    ).toBeTruthy();
  });

  it("contains no unsupported certification claims or private-domain data", async () => {
    render(<OperatorComplianceReadinessCenter organizations={oneOrg} />);
    await screen.findByText("EI-SBJ");
    expect(document.body.textContent).not.toMatch(
      /Certified|Fully compliant|Safe to fly|Flight authorized|Regulator approved|review_note|storage_object_reference|customer identity|passenger identity|payment|provider/i,
    );
  });
});
