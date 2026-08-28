"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Badge,
  Card,
  Container,
  EmptyState,
  LoadingState,
  PageHeading,
} from "@/components/ui/primitives";
import { portalApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { OperatorAircraft } from "@/lib/api/types";

export function OperatorAircraftDetail({
  aircraftId,
  organizations,
}: {
  readonly aircraftId: string;
  readonly organizations: readonly { id: string; role: string }[];
}) {
  const [organizationId, setOrganizationId] = useState(
    organizations.length === 1 ? organizations[0].id : "",
  );
  const [item, setItem] = useState<OperatorAircraft | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "missing">(
    "loading",
  );
  const epochRef = useRef(0);
  useEffect(() => {
    if (!organizationId) return;
    const epoch = ++epochRef.current;
    const controller = new AbortController();
    portalApi
      .getOperatorAircraft(aircraftId, organizationId, controller.signal)
      .then((value) => {
        if (epoch === epochRef.current) setItem(value);
      })
      .catch((caught) => {
        if (caught instanceof DOMException && caught.name === "AbortError")
          return;
        if (epoch === epochRef.current)
          setStatus(
            caught instanceof ApiError && caught.status === 404
              ? "missing"
              : "error",
          );
      });
    return () => controller.abort();
  }, [aircraftId, organizationId]);
  return (
    <div className="operator-aircraft">
      <Container>
        <Link href="/operator/aircraft">← Aircraft inventory</Link>
        <PageHeading
          title="Aircraft details"
          description="Authoritative operator-safe aircraft facts."
        />
        {organizations.length > 1 ? (
          <label className="operator-org">
            Operator organization
            <select
              className="operator-org__select"
              value={organizationId}
              onChange={(event) => {
                epochRef.current += 1;
                setItem(null);
                setStatus("loading");
                setOrganizationId(event.target.value);
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
            description="Select an organization before aircraft details are requested."
          />
        ) : null}
        {organizationId && !item && status === "loading" ? (
          <LoadingState label="Loading aircraft details…" />
        ) : null}
        {status === "missing" ? (
          <EmptyState
            title="Aircraft not found"
            description="This aircraft is unavailable in the active operator organization."
          />
        ) : null}
        {status === "error" ? (
          <Alert tone="error" title="Aircraft details could not be loaded">
            No aircraft or eligibility facts have been inferred.
          </Alert>
        ) : null}
        {item ? (
          <Card className="operator-aircraft__detail">
            <header>
              <h2>{item.registration}</h2>
              <Badge tone={item.eligible ? "success" : "warning"}>
                {item.eligible
                  ? "Eligible for marketplace offers"
                  : "Not currently eligible"}
              </Badge>
            </header>
            <dl>
              <div>
                <dt>Manufacturer</dt>
                <dd>{item.manufacturer}</dd>
              </div>
              <div>
                <dt>Model</dt>
                <dd>{item.model}</dd>
              </div>
              <div>
                <dt>Category</dt>
                <dd>{item.category}</dd>
              </div>
              <div>
                <dt>Passenger capacity</dt>
                <dd>{item.passenger_capacity}</dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd>{item.status}</dd>
              </div>
            </dl>
            <p>
              Aircraft ownership, status, and compliance are revalidated by the
              server when an offer is submitted.
            </p>
          </Card>
        ) : null}
      </Container>
    </div>
  );
}
