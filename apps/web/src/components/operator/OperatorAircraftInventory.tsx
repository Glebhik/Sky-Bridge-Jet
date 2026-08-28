"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

import {
  Alert,
  Badge,
  Button,
  Card,
  Container,
  EmptyState,
  Field,
  LoadingState,
  PageHeading,
} from "@/components/ui/primitives";
import { portalApi } from "@/lib/api/client";
import type { OperatorAircraft, OperatorAircraftCreate } from "@/lib/api/types";

type Organization = {
  readonly id: string;
  readonly role: string;
  readonly canCreate: boolean;
};
type Scope = { readonly organizationId: string; readonly epoch: number };
type ReadScope = Scope & { readonly requestId: number };
const PAGE_SIZE = 20;
const EMPTY: OperatorAircraftCreate = {
  registration: "",
  manufacturer: "",
  model: "",
  category: "",
  passenger_capacity: 1,
};

export function OperatorAircraftInventory({
  organizations,
}: {
  readonly organizations: readonly Organization[];
}) {
  const initial = organizations.length === 1 ? organizations[0].id : "";
  const [organizationId, setOrganizationId] = useState(initial);
  const [items, setItems] = useState<readonly OperatorAircraft[] | null>(null);
  const [error, setError] = useState(false);
  const [form, setForm] = useState<OperatorAircraftCreate>(EMPTY);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(Boolean(initial));
  const [hasNext, setHasNext] = useState(false);
  const orgRef = useRef(initial);
  const epochRef = useRef(0);
  const requestRef = useRef(0);
  const offsetRef = useRef(0);
  const readRef = useRef<AbortController | null>(null);
  const mutationRef = useRef(new Map<string, symbol>());
  const active = organizations.find(
    (organization) => organization.id === organizationId,
  );

  const current = useCallback(
    (scope: Scope) =>
      scope.organizationId === orgRef.current &&
      scope.epoch === epochRef.current,
    [],
  );
  const currentRead = useCallback(
    (scope: ReadScope) =>
      current(scope) && scope.requestId === requestRef.current,
    [current],
  );
  const mutationKey = (scope: Scope) =>
    `${scope.organizationId}:${scope.epoch}`;
  const changeOrganization = useCallback((next: string) => {
    readRef.current?.abort();
    orgRef.current = next;
    epochRef.current += 1;
    requestRef.current += 1;
    setItems(null);
    setError(false);
    setCreateError(null);
    setForm(EMPTY);
    setCreating(false);
    setOffset(0);
    offsetRef.current = 0;
    setHasNext(false);
    setLoading(Boolean(next));
    setOrganizationId(next);
  }, []);

  const load = useCallback(
    async (org: string, requestedOffset: number) => {
      readRef.current?.abort();
      const controller = new AbortController();
      readRef.current = controller;
      const scope = {
        organizationId: org,
        epoch: epochRef.current,
        requestId: ++requestRef.current,
      };
      const previousOffset = offsetRef.current;
      offsetRef.current = requestedOffset;
      setOffset(requestedOffset);
      setLoading(true);
      setError(false);
      try {
        const value = await portalApi.listOperatorAircraftPage(
          org,
          { limit: PAGE_SIZE, offset: requestedOffset },
          controller.signal,
        );
        if (!currentRead(scope)) return;
        if (requestedOffset > 0 && value.length === 0) {
          offsetRef.current = previousOffset;
          setOffset(previousOffset);
          setHasNext(false);
          return;
        }
        setItems(value);
        setHasNext(value.length === PAGE_SIZE);
      } catch (caught) {
        if (caught instanceof DOMException && caught.name === "AbortError")
          return;
        if (currentRead(scope)) {
          offsetRef.current = previousOffset;
          setOffset(previousOffset);
          setError(true);
        }
      } finally {
        if (currentRead(scope)) setLoading(false);
      }
    },
    [currentRead],
  );

  useEffect(() => {
    if (!organizationId) return;
    let mounted = true;
    queueMicrotask(() => {
      if (mounted) void load(organizationId, 0);
    });
    return () => {
      mounted = false;
      readRef.current?.abort();
    };
  }, [organizationId, load]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!active?.canCreate || !organizationId) return;
    const scope = { organizationId, epoch: epochRef.current };
    const key = mutationKey(scope);
    if (mutationRef.current.has(key)) return;
    const token = Symbol("aircraft-create");
    mutationRef.current.set(key, token);
    setCreating(true);
    setCreateError(null);
    try {
      await portalApi.createOperatorAircraft(form, organizationId);
      if (current(scope)) {
        setForm(EMPTY);
        await load(organizationId, 0);
      }
    } catch {
      if (current(scope))
        setCreateError("Aircraft could not be created. No action was retried.");
    } finally {
      if (mutationRef.current.get(key) === token)
        mutationRef.current.delete(key);
      if (current(scope)) setCreating(false);
    }
  }

  return (
    <div className="operator-aircraft">
      <Container>
        <PageHeading
          title="Aircraft inventory"
          description="Operator-owned aircraft facts and marketplace eligibility for the active organization."
        />
        {organizations.length > 1 ? (
          <label className="operator-org">
            Operator organization
            <select
              className="operator-org__select"
              value={organizationId}
              onChange={(event) => changeOrganization(event.target.value)}
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
            description="Select an organization before aircraft data is requested."
          />
        ) : (
          <Button
            variant="secondary"
            disabled={loading}
            onClick={() => void load(organizationId, offset)}
          >
            Refresh aircraft
          </Button>
        )}
        {organizationId && error ? (
          <Alert tone="error" title="Aircraft could not be loaded">
            No eligibility conclusion has been inferred. Use Refresh aircraft to
            try again.
          </Alert>
        ) : null}
        {organizationId && items === null && loading && !error ? (
          <LoadingState label="Loading aircraft…" />
        ) : null}
        {organizationId && items?.length === 0 && !error ? (
          <EmptyState
            title="No aircraft found"
            description="This operator organization has no aircraft in its inventory."
          />
        ) : null}
        {items && items.length > 0 ? (
          <>
            <p className="operator-aircraft__page-status" role="status">
              {`Page ${Math.floor(offset / PAGE_SIZE) + 1} · up to ${PAGE_SIZE} aircraft on this page`}
            </p>
            <div className="operator-aircraft__grid">
              {items.map((aircraft) => (
                <Card
                  as="article"
                  className="operator-aircraft__card"
                  key={aircraft.id}
                >
                  <header>
                    <h2>{aircraft.registration}</h2>
                    <Badge tone={aircraft.eligible ? "success" : "warning"}>
                      {aircraft.eligible
                        ? "Eligible for marketplace offers"
                        : "Not currently eligible"}
                    </Badge>
                  </header>
                  <p>
                    {aircraft.manufacturer} {aircraft.model}
                  </p>
                  <dl>
                    <div>
                      <dt>Category</dt>
                      <dd>{aircraft.category}</dd>
                    </div>
                    <div>
                      <dt>Passenger capacity</dt>
                      <dd>{aircraft.passenger_capacity}</dd>
                    </div>
                    <div>
                      <dt>Status</dt>
                      <dd>{aircraft.status}</dd>
                    </div>
                  </dl>
                  <Link href={`/operator/aircraft/${aircraft.id}`}>
                    View aircraft details
                  </Link>
                </Card>
              ))}
            </div>
            <nav
              className="operator-aircraft__pagination"
              aria-label="Aircraft pages"
            >
              <Button
                variant="secondary"
                disabled={offset === 0}
                onClick={() =>
                  void load(organizationId, Math.max(0, offset - PAGE_SIZE))
                }
              >
                Previous
              </Button>
              <Button
                variant="secondary"
                disabled={!hasNext}
                onClick={() => void load(organizationId, offset + PAGE_SIZE)}
              >
                Next
              </Button>
            </nav>
          </>
        ) : null}
        {active?.canCreate ? (
          <Card className="operator-aircraft__create">
            <h2>Add aircraft</h2>
            <p>
              Eligibility is calculated by the server and may change when an
              offer is submitted.
            </p>
            {createError ? (
              <Alert tone="error" title="Aircraft not created">
                {createError}
              </Alert>
            ) : null}
            <form aria-busy={creating} onSubmit={(event) => void submit(event)}>
              <Field
                id="registration"
                label="Registration"
                required
                value={form.registration}
                onChange={(e) =>
                  setForm({ ...form, registration: e.target.value })
                }
              />
              <Field
                id="manufacturer"
                label="Manufacturer"
                required
                value={form.manufacturer}
                onChange={(e) =>
                  setForm({ ...form, manufacturer: e.target.value })
                }
              />
              <Field
                id="model"
                label="Model"
                required
                value={form.model}
                onChange={(e) => setForm({ ...form, model: e.target.value })}
              />
              <Field
                id="category"
                label="Category"
                required
                value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value })}
              />
              <Field
                id="capacity"
                label="Passenger capacity"
                required
                type="number"
                min={1}
                value={form.passenger_capacity}
                onChange={(e) =>
                  setForm({
                    ...form,
                    passenger_capacity: Number(e.target.value),
                  })
                }
              />
              <Button type="submit" disabled={creating}>
                {creating ? "Adding aircraft…" : "Add aircraft"}
              </Button>
            </form>
          </Card>
        ) : null}
      </Container>
    </div>
  );
}
