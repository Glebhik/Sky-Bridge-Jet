import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PlatformComplianceDetail } from "@/components/platform/PlatformComplianceDetail";
import { portalApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { PlatformAdmission } from "@/lib/api/types";

vi.mock("@/lib/api/client", () => ({
  portalApi: {
    getPlatformAdmission: vi.fn(),
    listPlatformComplianceAudit: vi.fn(),
    reviewPlatformAdmission: vi.fn(),
    getPlatformEvidence: vi.fn(),
    reviewPlatformEvidence: vi.fn(),
    getPlatformAuthorization: vi.fn(),
    reviewPlatformAuthorization: vi.fn(),
  },
}));

const admission: PlatformAdmission = {
  id: "123e4567-e89b-42d3-a456-426614174000",
  operator_id: "123e4567-e89b-42d3-a456-426614174001",
  operator_legal_name: "Review Aviation",
  operator_trading_name: null,
  operator_country_code: "IE",
  status: "UNDER_REVIEW" as const,
  reason_code: null,
  review_note: null,
  submitted_at: "2026-08-28T10:00:00Z",
  reviewed_at: null,
  created_at: "2026-08-28T09:00:00Z",
  updated_at: "2026-08-28T10:00:00Z",
};

const otherAdmission = {
  ...admission,
  id: "223e4567-e89b-42d3-a456-426614174000",
  operator_id: "223e4567-e89b-42d3-a456-426614174001",
  operator_legal_name: "Current Aviation",
};

const evidence = {
  id: admission.id,
  operator_id: "323e4567-e89b-42d3-a456-426614174001",
  operator_legal_name: "Evidence Aviation",
  operator_trading_name: null,
  aircraft_id: null,
  aircraft_registration: null,
  evidence_type: "INSURANCE",
  status: "UNDER_REVIEW" as const,
  effective_status: "UNDER_REVIEW",
  authority_basis: null,
  reference_number: null,
  issuing_authority: null,
  jurisdiction: null,
  insurer_name: null,
  has_storage_object: false,
  effective_date: null,
  expiry_date: null,
  submitted_at: "2026-08-28T10:00:00Z",
  reviewed_at: null,
  review_reason_code: null,
  review_note: null,
  created_at: "2026-08-28T09:00:00Z",
  updated_at: "2026-08-28T10:00:00Z",
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, reject, resolve };
}

describe("PlatformComplianceDetail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(portalApi.getPlatformAdmission)
      .mockResolvedValueOnce(admission)
      .mockResolvedValue({ ...admission, status: "APPROVED" });
    vi.mocked(portalApi.listPlatformComplianceAudit).mockResolvedValue([]);
    vi.mocked(portalApi.reviewPlatformAdmission).mockResolvedValue({
      ...admission,
      status: "APPROVED",
    });
  });

  it("requires explicit confirmation and sends no browser actor identity", async () => {
    render(<PlatformComplianceDetail kind="admissions" id={admission.id} />);
    expect(await screen.findByText("Review Aviation")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "APPROVE" }));
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm decision" }));
    await screen.findByText("APPROVED");
    expect(portalApi.reviewPlatformAdmission).toHaveBeenCalledWith(
      admission.id,
      { action: "APPROVE" },
    );
  });

  it("invalidates an A confirmation before B can submit it", async () => {
    vi.mocked(portalApi.getPlatformAdmission).mockReset();
    vi.mocked(portalApi.getPlatformAdmission)
      .mockResolvedValueOnce(admission)
      .mockResolvedValue(otherAdmission);
    const view = render(
      <PlatformComplianceDetail kind="admissions" id={admission.id} />,
    );
    expect(await screen.findByText("Review Aviation")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "APPROVE" }));
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();

    view.rerender(
      <PlatformComplianceDetail kind="admissions" id={otherAdmission.id} />,
    );
    expect(await screen.findByText("Current Aviation")).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(portalApi.reviewPlatformAdmission).not.toHaveBeenCalled();
  });

  it("discards a late A mutation success after navigation to B", async () => {
    const mutation = deferred<typeof admission>();
    vi.mocked(portalApi.getPlatformAdmission).mockReset();
    vi.mocked(portalApi.getPlatformAdmission)
      .mockResolvedValueOnce(admission)
      .mockResolvedValue(otherAdmission);
    vi.mocked(portalApi.reviewPlatformAdmission).mockReturnValue(
      mutation.promise,
    );
    const view = render(
      <PlatformComplianceDetail kind="admissions" id={admission.id} />,
    );
    expect(await screen.findByText("Review Aviation")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "APPROVE" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm decision" }));
    view.rerender(
      <PlatformComplianceDetail kind="admissions" id={otherAdmission.id} />,
    );
    expect(await screen.findByText("Current Aviation")).toBeInTheDocument();

    mutation.resolve({ ...admission, status: "APPROVED" });
    await waitFor(() =>
      expect(screen.getByText("Current Aviation")).toBeInTheDocument(),
    );
    expect(screen.queryByText("Review Aviation")).not.toBeInTheDocument();
  });

  it.each([
    ["conflict", new ApiError(409, "CONFLICT", "stale", "conflict")],
    ["unknown outcome", new TypeError("network lost")],
  ])("ignores a stale A %s after navigation to B", async (_label, failure) => {
    const mutation = deferred<typeof admission>();
    vi.mocked(portalApi.getPlatformAdmission).mockReset();
    vi.mocked(portalApi.getPlatformAdmission)
      .mockResolvedValueOnce(admission)
      .mockResolvedValue(otherAdmission);
    vi.mocked(portalApi.reviewPlatformAdmission).mockReturnValue(
      mutation.promise,
    );
    const view = render(
      <PlatformComplianceDetail kind="admissions" id={admission.id} />,
    );
    expect(await screen.findByText("Review Aviation")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "APPROVE" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm decision" }));
    view.rerender(
      <PlatformComplianceDetail kind="admissions" id={otherAdmission.id} />,
    );
    expect(await screen.findByText("Current Aviation")).toBeInTheDocument();

    mutation.reject(failure);
    await waitFor(() =>
      expect(screen.getByText("Current Aviation")).toBeInTheDocument(),
    );
    expect(
      screen.queryByText(/decision outcome is not confirmed/i),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/resource changed before this decision/i),
    ).not.toBeInTheDocument();
  });

  it("rejects an old A1 result after A1 to B to A2 navigation", async () => {
    const mutation = deferred<typeof admission>();
    const currentA = {
      ...admission,
      operator_legal_name: "Current A generation",
    };
    vi.mocked(portalApi.getPlatformAdmission).mockReset();
    vi.mocked(portalApi.getPlatformAdmission)
      .mockResolvedValueOnce(admission)
      .mockResolvedValueOnce(otherAdmission)
      .mockResolvedValue(currentA);
    vi.mocked(portalApi.reviewPlatformAdmission).mockReturnValue(
      mutation.promise,
    );
    const view = render(
      <PlatformComplianceDetail kind="admissions" id={admission.id} />,
    );
    expect(await screen.findByText("Review Aviation")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "APPROVE" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm decision" }));
    view.rerender(
      <PlatformComplianceDetail kind="admissions" id={otherAdmission.id} />,
    );
    expect(await screen.findByText("Current Aviation")).toBeInTheDocument();
    view.rerender(
      <PlatformComplianceDetail kind="admissions" id={admission.id} />,
    );
    expect(await screen.findByText("Current A generation")).toBeInTheDocument();

    mutation.resolve({ ...admission, status: "APPROVED" });
    await waitFor(() =>
      expect(screen.getByText("Current A generation")).toBeInTheDocument(),
    );
    expect(screen.queryByText("Review Aviation")).not.toBeInTheDocument();
  });

  it("keeps an old admission result out of a same-UUID evidence detail", async () => {
    const mutation = deferred<typeof admission>();
    vi.mocked(portalApi.getPlatformAdmission).mockReset();
    vi.mocked(portalApi.getPlatformAdmission).mockResolvedValue(admission);
    vi.mocked(portalApi.getPlatformEvidence).mockResolvedValue(evidence);
    vi.mocked(portalApi.reviewPlatformAdmission).mockReturnValue(
      mutation.promise,
    );
    const view = render(
      <PlatformComplianceDetail kind="admissions" id={admission.id} />,
    );
    expect(await screen.findByText("Review Aviation")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "APPROVE" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm decision" }));
    view.rerender(
      <PlatformComplianceDetail kind="evidence" id={admission.id} />,
    );
    expect(await screen.findByText("Evidence Aviation")).toBeInTheDocument();

    mutation.resolve({ ...admission, status: "APPROVED" });
    await waitFor(() =>
      expect(screen.getByText("Evidence Aviation")).toBeInTheDocument(),
    );
    expect(screen.queryByText("Review Aviation")).not.toBeInTheDocument();
  });

  it("keeps delayed detail and audit reads scoped to their resource", async () => {
    const detailA = deferred<typeof admission>();
    const auditA = deferred<readonly never[]>();
    vi.mocked(portalApi.getPlatformAdmission).mockReset();
    vi.mocked(portalApi.getPlatformAdmission).mockImplementation((id) =>
      id === admission.id ? detailA.promise : Promise.resolve(otherAdmission),
    );
    vi.mocked(portalApi.listPlatformComplianceAudit).mockImplementation(
      (_kind, id) =>
        id === admission.id ? auditA.promise : Promise.resolve([]),
    );
    const view = render(
      <PlatformComplianceDetail kind="admissions" id={admission.id} />,
    );
    view.rerender(
      <PlatformComplianceDetail kind="admissions" id={otherAdmission.id} />,
    );
    expect(await screen.findByText("Current Aviation")).toBeInTheDocument();
    detailA.resolve(admission);
    auditA.resolve([]);
    await waitFor(() =>
      expect(screen.getByText("Current Aviation")).toBeInTheDocument(),
    );
    expect(screen.queryByText("Review Aviation")).not.toBeInTheDocument();
  });

  it("issues one POST for rapid duplicate confirmation", async () => {
    const mutation = deferred<typeof admission>();
    vi.mocked(portalApi.reviewPlatformAdmission).mockReturnValue(
      mutation.promise,
    );
    render(<PlatformComplianceDetail kind="admissions" id={admission.id} />);
    expect(await screen.findByText("Review Aviation")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "APPROVE" }));
    const confirmButton = screen.getByRole("button", {
      name: "Confirm decision",
    });
    fireEvent.click(confirmButton);
    fireEvent.click(confirmButton);
    expect(portalApi.reviewPlatformAdmission).toHaveBeenCalledTimes(1);
    mutation.resolve({ ...admission, status: "APPROVED" });
  });

  it("does not let old A cleanup release an in-flight B mutation", async () => {
    const mutationA = deferred<typeof admission>();
    const mutationB = deferred<typeof admission>();
    vi.mocked(portalApi.getPlatformAdmission).mockReset();
    vi.mocked(portalApi.getPlatformAdmission).mockImplementation((id) =>
      Promise.resolve(id === admission.id ? admission : otherAdmission),
    );
    vi.mocked(portalApi.reviewPlatformAdmission).mockImplementation((id) =>
      id === admission.id ? mutationA.promise : mutationB.promise,
    );
    const view = render(
      <PlatformComplianceDetail kind="admissions" id={admission.id} />,
    );
    expect(await screen.findByText("Review Aviation")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "APPROVE" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm decision" }));
    view.rerender(
      <PlatformComplianceDetail kind="admissions" id={otherAdmission.id} />,
    );
    expect(await screen.findByText("Current Aviation")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "APPROVE" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm decision" }));
    mutationA.resolve({ ...admission, status: "APPROVED" });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Confirm decision" }),
      ).toBeDisabled(),
    );
    expect(portalApi.reviewPlatformAdmission).toHaveBeenCalledTimes(2);
    mutationB.resolve({ ...otherAdmission, status: "APPROVED" });
  });

  it.each([
    ["conflict", new ApiError(409, "CONFLICT", "stale", "conflict")],
    ["unknown outcome", new TypeError("network lost")],
  ])("rejects old A1 %s after returning to A2", async (_label, failure) => {
    const mutation = deferred<typeof admission>();
    const currentA = {
      ...admission,
      operator_legal_name: "Current A generation",
    };
    vi.mocked(portalApi.getPlatformAdmission).mockReset();
    vi.mocked(portalApi.getPlatformAdmission)
      .mockResolvedValueOnce(admission)
      .mockResolvedValueOnce(otherAdmission)
      .mockResolvedValue(currentA);
    vi.mocked(portalApi.reviewPlatformAdmission).mockReturnValue(
      mutation.promise,
    );
    const view = render(
      <PlatformComplianceDetail kind="admissions" id={admission.id} />,
    );
    expect(await screen.findByText("Review Aviation")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "APPROVE" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm decision" }));
    view.rerender(
      <PlatformComplianceDetail kind="admissions" id={otherAdmission.id} />,
    );
    expect(await screen.findByText("Current Aviation")).toBeInTheDocument();
    view.rerender(
      <PlatformComplianceDetail kind="admissions" id={admission.id} />,
    );
    expect(await screen.findByText("Current A generation")).toBeInTheDocument();
    mutation.reject(failure);
    await waitFor(() =>
      expect(screen.getByText("Current A generation")).toBeInTheDocument(),
    );
    expect(
      screen.queryByText(/decision outcome is not confirmed/i),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/resource changed before this decision/i),
    ).not.toBeInTheDocument();
  });

  it("refreshes once on a current 409 without retrying the mutation", async () => {
    vi.mocked(portalApi.getPlatformAdmission).mockReset();
    vi.mocked(portalApi.getPlatformAdmission)
      .mockResolvedValueOnce(admission)
      .mockResolvedValue({ ...admission, status: "APPROVED" });
    vi.mocked(portalApi.reviewPlatformAdmission).mockRejectedValue(
      new ApiError(409, "CONFLICT", "stale", "conflict"),
    );
    render(<PlatformComplianceDetail kind="admissions" id={admission.id} />);
    expect(await screen.findByText("Review Aviation")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "APPROVE" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm decision" }));
    expect(
      await screen.findByText(/authoritative state was refreshed/i),
    ).toBeInTheDocument();
    expect(portalApi.reviewPlatformAdmission).toHaveBeenCalledTimes(1);
    expect(portalApi.getPlatformAdmission).toHaveBeenCalledTimes(2);
  });

  it("requires an authoritative refresh after a current unknown outcome", async () => {
    vi.mocked(portalApi.reviewPlatformAdmission).mockRejectedValue(
      new TypeError("network lost"),
    );
    render(<PlatformComplianceDetail kind="admissions" id={admission.id} />);
    expect(await screen.findByText("Review Aviation")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "APPROVE" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm decision" }));
    expect(
      await screen.findByText(/decision outcome is not confirmed/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "APPROVE" })).toBeDisabled();
    expect(portalApi.reviewPlatformAdmission).toHaveBeenCalledTimes(1);
  });
});
