"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  Alert,
  Button,
  Card,
  Container,
  EmptyState,
  LoadingState,
  PageHeading,
} from "@/components/ui/primitives";
import { portalApi } from "@/lib/api/client";
import type {
  EligibilityReasonCode,
  OperatorAdmissionStatus,
  OperatorAircraft,
  OperatorComplianceReadiness,
} from "@/lib/api/types";

type Organization = { readonly id: string; readonly role: string };
type Scope = { readonly organizationId: string; readonly epoch: number };

const ADMISSION_LABELS: Record<OperatorAdmissionStatus, string> = {
  DRAFT: "Draft",
  SUBMITTED: "Submitted",
  UNDER_REVIEW: "Under review",
  APPROVED: "Approved for marketplace admission",
  REJECTED: "Rejected",
  SUSPENDED: "Suspended",
};

const BLOCKER_LABELS: Record<EligibilityReasonCode, string> = {
  OPERATOR_NOT_ADMITTED: "Operator marketplace admission is not approved",
  OPERATOR_UNDER_REVIEW: "Operator marketplace admission is under review",
  OPERATOR_REJECTED: "Operator marketplace admission was rejected",
  OPERATOR_SUSPENDED: "Operator marketplace admission is suspended",
  AUTHORITY_NOT_VERIFIED: "Operating authority is not verified",
  AUTHORITY_EXPIRED: "Verified operating authority has expired",
  INSURANCE_NOT_VERIFIED: "Insurance is not verified",
  INSURANCE_EXPIRED: "Verified insurance has expired",
  AIRCRAFT_NOT_AUTHORIZED: "Aircraft is not authorized for marketplace use",
  AIRCRAFT_AUTHORIZATION_SUSPENDED:
    "Aircraft marketplace authorization is suspended",
  AIRCRAFT_NOT_OPERATED_BY_OPERATOR:
    "Aircraft is not operated by this organization",
};

export function admissionLabel(status: OperatorAdmissionStatus | null): string {
  return status === null
    ? "No operator admission record is currently available."
    : ADMISSION_LABELS[status];
}

export function blockerLabel(code: string): string {
  return (
    BLOCKER_LABELS[code as EligibilityReasonCode] ??
    "Additional compliance requirement"
  );
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString("en-IE");
}

export function OperatorComplianceReadinessCenter({
  organizations,
}: {
  readonly organizations: readonly Organization[];
}) {
  const initialOrganization =
    organizations.length === 1 ? organizations[0].id : "";
  const [organizationId, setOrganizationId] = useState(initialOrganization);
  const [readiness, setReadiness] =
    useState<OperatorComplianceReadiness | null>(null);
  const [aircraft, setAircraft] = useState<readonly OperatorAircraft[] | null>(
    null,
  );
  const [readinessError, setReadinessError] = useState(false);
  const [aircraftError, setAircraftError] = useState(false);
  const readinessControllerRef = useRef<AbortController | null>(null);
  const aircraftControllerRef = useRef<AbortController | null>(null);
  const organizationRef = useRef(initialOrganization);
  const epochRef = useRef(0);

  const isCurrent = useCallback(
    (scope: Scope) =>
      scope.organizationId === organizationRef.current &&
      scope.epoch === epochRef.current,
    [],
  );

  const clearScope = useCallback((nextOrganizationId: string) => {
    readinessControllerRef.current?.abort();
    aircraftControllerRef.current?.abort();
    organizationRef.current = nextOrganizationId;
    epochRef.current += 1;
    setReadiness(null);
    setAircraft(null);
    setReadinessError(false);
    setAircraftError(false);
  }, []);

  const load = useCallback(async () => {
    const activeOrganizationId = organizationRef.current;
    if (!activeOrganizationId) return;
    readinessControllerRef.current?.abort();
    aircraftControllerRef.current?.abort();
    const readinessController = new AbortController();
    const aircraftController = new AbortController();
    readinessControllerRef.current = readinessController;
    aircraftControllerRef.current = aircraftController;
    const scope = {
      organizationId: activeOrganizationId,
      epoch: ++epochRef.current,
    };
    setReadiness(null);
    setAircraft(null);
    setReadinessError(false);
    setAircraftError(false);

    const readinessRequest = portalApi
      .getOperatorComplianceReadiness(
        activeOrganizationId,
        readinessController.signal,
      )
      .then((next) => {
        if (isCurrent(scope)) setReadiness(next);
      })
      .catch((caught: unknown) => {
        if (caught instanceof DOMException && caught.name === "AbortError")
          return;
        if (isCurrent(scope)) setReadinessError(true);
      });
    const aircraftRequest = portalApi
      .listOperatorAircraft(activeOrganizationId, aircraftController.signal)
      .then((next) => {
        if (isCurrent(scope)) setAircraft(next);
      })
      .catch((caught: unknown) => {
        if (caught instanceof DOMException && caught.name === "AbortError")
          return;
        if (isCurrent(scope)) setAircraftError(true);
      });
    await Promise.allSettled([readinessRequest, aircraftRequest]);
  }, [isCurrent]);

  useEffect(() => {
    if (!organizationId) return;
    let active = true;
    queueMicrotask(() => {
      if (active) void load();
    });
    return () => {
      active = false;
      readinessControllerRef.current?.abort();
      aircraftControllerRef.current?.abort();
    };
  }, [organizationId, load]);

  if (organizations.length === 0)
    return (
      <Container>
        <Alert tone="error" title="Operator access required">
          This area is available only to members of an operator organization.
        </Alert>
      </Container>
    );

  const loadingReadiness =
    Boolean(organizationId) && !readiness && !readinessError;
  const loadingAircraft =
    Boolean(organizationId) && !aircraft && !aircraftError;

  return (
    <div className="operator-compliance">
      <Container>
        <PageHeading
          title="Compliance readiness"
          description="Factual marketplace admission and aircraft readiness for the active operator organization."
        />
        {organizations.length > 1 ? (
          <label className="operator-org">
            Operator organization
            <select
              className="operator-org__select"
              value={organizationId}
              onChange={(event) => {
                const next = event.target.value;
                clearScope(next);
                setOrganizationId(next);
              }}
            >
              <option value="">Choose operator organization</option>
              {organizations.map((organization, index) => (
                <option key={organization.id} value={organization.id}>
                  Operator organization {index + 1} — {organization.role}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {!organizationId ? (
          <EmptyState
            title="Choose operator organization"
            description="Select the operator organization whose readiness you want to view."
          />
        ) : (
          <div className="operator-compliance__toolbar">
            <Button
              variant="secondary"
              disabled={loadingReadiness || loadingAircraft}
              onClick={() => void load()}
            >
              Refresh readiness
            </Button>
          </div>
        )}

        {organizationId ? (
          <div className="operator-compliance__sections">
            <section aria-labelledby="operator-readiness-heading">
              <h2 id="operator-readiness-heading">Operator readiness</h2>
              {readinessError ? (
                <Alert
                  tone="error"
                  title="Operator readiness could not be loaded"
                >
                  Readiness is unavailable; this does not indicate a compliance
                  outcome.
                </Alert>
              ) : loadingReadiness ? (
                <LoadingState label="Loading operator readiness…" />
              ) : readiness ? (
                <Card className="operator-compliance__card">
                  <dl className="operator-compliance__facts">
                    <div>
                      <dt>Admission status</dt>
                      <dd>{admissionLabel(readiness.admission_status)}</dd>
                    </div>
                    <div>
                      <dt>Marketplace participation</dt>
                      <dd>
                        {readiness.marketplace_eligible
                          ? "Currently eligible for Sky Bridge Jet marketplace participation."
                          : "Not currently eligible for marketplace participation."}
                      </dd>
                    </div>
                    {readiness.created_at ? (
                      <div>
                        <dt>Admission record created</dt>
                        <dd>
                          <time dateTime={readiness.created_at}>
                            {formatDate(readiness.created_at)}
                          </time>
                        </dd>
                      </div>
                    ) : null}
                    {readiness.updated_at ? (
                      <div>
                        <dt>Admission record updated</dt>
                        <dd>
                          <time dateTime={readiness.updated_at}>
                            {formatDate(readiness.updated_at)}
                          </time>
                        </dd>
                      </div>
                    ) : null}
                  </dl>
                  {readiness.blockers.length > 0 ? (
                    <div className="operator-compliance__blockers">
                      <h3>Current marketplace blockers</h3>
                      <ul>
                        {readiness.blockers.map((blocker, index) => (
                          <li key={`${blocker}-${index}`}>
                            {blockerLabel(blocker)}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : (
                    <p className="operator-compliance__clear">
                      No marketplace readiness blockers were reported.
                    </p>
                  )}
                </Card>
              ) : null}
            </section>

            <section aria-labelledby="aircraft-readiness-heading">
              <h2 id="aircraft-readiness-heading">Aircraft readiness</h2>
              {aircraftError ? (
                <Alert
                  tone="error"
                  title="Aircraft readiness could not be loaded"
                >
                  Aircraft information is unavailable. Operator admission status
                  is unchanged.
                </Alert>
              ) : loadingAircraft ? (
                <LoadingState label="Loading aircraft readiness…" />
              ) : aircraft?.length === 0 ? (
                <EmptyState
                  title="No owned aircraft available"
                  description="No aircraft are currently returned for this operator organization."
                />
              ) : aircraft ? (
                <ul className="operator-compliance__aircraft">
                  {aircraft.map((item) => (
                    <li key={item.id}>
                      <Card
                        as="article"
                        className="operator-compliance__aircraft-card"
                      >
                        <header>
                          <h3>{item.registration}</h3>
                          <strong>
                            {item.eligible
                              ? "Currently eligible for marketplace offers"
                              : "Not currently eligible"}
                          </strong>
                        </header>
                        <p>
                          {item.manufacturer} {item.model}
                        </p>
                        <dl>
                          <div>
                            <dt>Category</dt>
                            <dd>{item.category}</dd>
                          </div>
                          <div>
                            <dt>Aircraft status</dt>
                            <dd>{item.status}</dd>
                          </div>
                          <div>
                            <dt>Passenger capacity</dt>
                            <dd>{item.passenger_capacity}</dd>
                          </div>
                        </dl>
                      </Card>
                    </li>
                  ))}
                </ul>
              ) : null}
            </section>
          </div>
        ) : null}

        {organizationId ? (
          <aside
            className="operator-compliance__boundary"
            aria-label="Marketplace authority"
          >
            Readiness controls whether marketplace offer operations may succeed.
            The server revalidates every offer command. It does not guarantee
            aircraft availability, crew, route permits, slots, customer
            acceptance, or booking confirmation.
          </aside>
        ) : null}
      </Container>
    </div>
  );
}
