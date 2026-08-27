"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

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
import { ApiError } from "@/lib/api/errors";
import type {
  OperatorAircraft,
  OperatorOffer,
  OperatorOfferCommand,
  OperatorOpportunity,
} from "@/lib/api/types";
import {
  decimalToMinorUnits,
  formatOperatorMoney,
  minorUnitsToDecimal,
} from "@/lib/operator/offers";

type Organization = {
  readonly id: string;
  readonly role: string;
  readonly canManage: boolean;
};
type Editor = { readonly tripId: string; readonly offerId?: string };
type OrganizationScope = {
  readonly organizationId: string;
  readonly epoch: number;
};
type FormState = {
  aircraftId: string;
  currency: "EUR" | "GBP" | "USD";
  operatorAmount: string;
  taxAmount: string;
  validUntil: string;
  operatorNotes: string;
  cancellationPolicy: string;
  includedServices: string;
  excludedServices: string;
};

const EMPTY_FORM: FormState = {
  aircraftId: "",
  currency: "EUR",
  operatorAmount: "",
  taxAmount: "0.00",
  validUntil: "",
  operatorNotes: "",
  cancellationPolicy: "",
  includedServices: "",
  excludedServices: "",
};

function formFromOffer(offer: OperatorOffer): FormState {
  return {
    aircraftId: offer.aircraft_id,
    currency: offer.currency,
    operatorAmount: minorUnitsToDecimal(offer.operator_amount_minor),
    taxAmount: minorUnitsToDecimal(offer.tax_amount_minor),
    validUntil: offer.valid_until ? offer.valid_until.slice(0, 16) : "",
    operatorNotes: offer.operator_notes ?? "",
    cancellationPolicy: offer.cancellation_policy ?? "",
    includedServices: offer.included_services ?? "",
    excludedServices: offer.excluded_services ?? "",
  };
}

function nullable(value: string): string | null {
  return value.trim() || null;
}

export function OperatorOpportunityMarketplace({
  organizations,
}: {
  readonly organizations: readonly Organization[];
}) {
  const [organizationId, setOrganizationId] = useState(
    organizations.length === 1 ? organizations[0].id : "",
  );
  const [opportunities, setOpportunities] = useState<
    readonly OperatorOpportunity[] | null
  >(null);
  const [aircraft, setAircraft] = useState<readonly OperatorAircraft[] | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [details, setDetails] = useState<
    Readonly<Record<string, OperatorOffer>>
  >({});
  const [pending, setPending] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const epochRef = useRef(0);
  const organizationRef = useRef(organizationId);
  const mutationTokens = useRef(new Map<string, symbol>());
  const [mutatingOrganizations, setMutatingOrganizations] = useState<
    ReadonlySet<string>
  >(new Set());
  const activeOrganization = organizations.find(
    (item) => item.id === organizationId,
  );

  const busy =
    pending ||
    (organizationId !== "" && mutatingOrganizations.has(organizationId));

  function captureScope(): OrganizationScope {
    return {
      organizationId: organizationRef.current,
      epoch: epochRef.current,
    };
  }

  function isCurrentScope(scope: OrganizationScope): boolean {
    return (
      scope.organizationId === organizationRef.current &&
      scope.epoch === epochRef.current
    );
  }

  function acquireMutation(scope: OrganizationScope): symbol | null {
    if (mutationTokens.current.has(scope.organizationId)) return null;
    const token = Symbol(scope.organizationId);
    mutationTokens.current.set(scope.organizationId, token);
    setMutatingOrganizations((current) =>
      new Set(current).add(scope.organizationId),
    );
    return token;
  }

  function releaseMutation(scope: OrganizationScope, token: symbol): void {
    if (mutationTokens.current.get(scope.organizationId) !== token) return;
    mutationTokens.current.delete(scope.organizationId);
    setMutatingOrganizations((current) => {
      const next = new Set(current);
      next.delete(scope.organizationId);
      return next;
    });
  }

  const resetScopedState = useCallback((nextOrganizationId: string) => {
    abortRef.current?.abort();
    organizationRef.current = nextOrganizationId;
    epochRef.current += 1;
    setOpportunities(null);
    setAircraft(null);
    setError(null);
    setEditor(null);
    setDetails({});
    setForm(EMPTY_FORM);
    setPending(false);
  }, []);

  const load = useCallback(async (orgId: string) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const epoch = ++epochRef.current;
    const scope = { organizationId: orgId, epoch };
    setError(null);
    try {
      const [nextOpportunities, nextAircraft] = await Promise.all([
        portalApi.listOperatorOpportunities(orgId, controller.signal),
        portalApi.listOperatorAircraft(orgId, controller.signal),
      ]);
      if (isCurrentScope(scope)) {
        setOpportunities(nextOpportunities);
        setAircraft(nextAircraft);
      }
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError")
        return;
      if (isCurrentScope(scope)) {
        setOpportunities([]);
        setAircraft([]);
        setError("Opportunities could not be loaded. No action was retried.");
      }
    }
  }, []);

  useEffect(() => {
    if (!organizationId) return;
    let active = true;
    queueMicrotask(() => {
      if (active) void load(organizationId);
    });
    return () => {
      active = false;
      abortRef.current?.abort();
    };
  }, [organizationId, load]);

  function updateOwnOffer(authoritative: OperatorOffer) {
    setDetails((current) => ({
      ...current,
      [authoritative.id]: authoritative,
    }));
    setOpportunities(
      (current) =>
        current?.map((opportunity) =>
          opportunity.trip_request_id !== authoritative.trip_request_id
            ? opportunity
            : {
                ...opportunity,
                own_offers: opportunity.own_offers.some(
                  (offer) => offer.offer_id === authoritative.id,
                )
                  ? opportunity.own_offers.map((offer) =>
                      offer.offer_id === authoritative.id
                        ? {
                            offer_id: authoritative.id,
                            status: authoritative.status,
                          }
                        : offer,
                    )
                  : [
                      ...opportunity.own_offers,
                      {
                        offer_id: authoritative.id,
                        status: authoritative.status,
                      },
                    ],
              },
        ) ?? current,
    );
  }

  async function authoritativeRefresh(
    offerId: string,
    scope: OrganizationScope,
  ) {
    if (!isCurrentScope(scope)) return;
    try {
      const offer = await portalApi.getOperatorOffer(
        offerId,
        scope.organizationId,
      );
      if (!isCurrentScope(scope)) return;
      updateOwnOffer(offer);
      if (offer.status === "DRAFT") setForm(formFromOffer(offer));
      else setEditor(null);
    } catch {
      if (isCurrentScope(scope)) setEditor(null);
    }
  }

  async function openDraft(tripId: string, offerId?: string) {
    if (!activeOrganization?.canManage || busy) return;
    const scope = captureScope();
    setError(null);
    if (!offerId) {
      setEditor({ tripId });
      setForm(EMPTY_FORM);
      return;
    }
    const cached = details[offerId];
    if (cached) {
      setEditor({ tripId, offerId });
      setForm(formFromOffer(cached));
      return;
    }
    setPending(true);
    try {
      const offer = await portalApi.getOperatorOffer(
        offerId,
        scope.organizationId,
      );
      if (!isCurrentScope(scope)) return;
      if (offer.status !== "DRAFT") {
        updateOwnOffer(offer);
        setError("Only a DRAFT offer can be edited.");
        return;
      }
      updateOwnOffer(offer);
      setEditor({ tripId, offerId });
      setForm(formFromOffer(offer));
    } catch {
      if (isCurrentScope(scope))
        setError("The authoritative offer could not be loaded.");
    } finally {
      if (isCurrentScope(scope)) setPending(false);
    }
  }

  function command(): OperatorOfferCommand | null {
    const amount = decimalToMinorUnits(form.operatorAmount);
    const tax = decimalToMinorUnits(form.taxAmount);
    if (amount === null || tax === null) return null;
    return {
      currency: form.currency,
      operator_amount_minor: amount,
      tax_amount_minor: tax,
      valid_until: form.validUntil
        ? new Date(form.validUntil).toISOString()
        : null,
      operator_notes: nullable(form.operatorNotes),
      cancellation_policy: nullable(form.cancellationPolicy),
      included_services: nullable(form.includedServices),
      excluded_services: nullable(form.excludedServices),
    };
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!editor) return;
    const body = command();
    if (!body || (!editor.offerId && !form.aircraftId)) {
      setError("Enter valid amounts and choose an eligible aircraft.");
      return;
    }
    const scope = captureScope();
    const token = acquireMutation(scope);
    if (token === null) return;
    setError(null);
    try {
      const offer = editor.offerId
        ? await portalApi.updateOperatorOffer(
            editor.offerId,
            body,
            scope.organizationId,
          )
        : await portalApi.createOperatorOffer(
            {
              ...body,
              trip_request_id: editor.tripId,
              aircraft_id: form.aircraftId,
              currency: form.currency,
              operator_amount_minor: body.operator_amount_minor!,
            },
            scope.organizationId,
          );
      if (!isCurrentScope(scope)) return;
      updateOwnOffer(offer);
      setEditor(null);
    } catch (caught) {
      if (!isCurrentScope(scope)) return;
      if (
        caught instanceof ApiError &&
        caught.status === 409 &&
        editor.offerId
      ) {
        await authoritativeRefresh(editor.offerId, scope);
        if (!isCurrentScope(scope)) return;
        setError(
          "The offer changed. Its authoritative state was refreshed; your change was not retried.",
        );
      } else setError("The offer could not be saved. No action was retried.");
    } finally {
      releaseMutation(scope, token);
    }
  }

  async function transition(offerId: string, action: "submit" | "withdraw") {
    const scope = captureScope();
    const token = acquireMutation(scope);
    if (token === null) return;
    setError(null);
    try {
      const offer =
        action === "submit"
          ? await portalApi.submitOperatorOffer(offerId, scope.organizationId)
          : await portalApi.withdrawOperatorOffer(
              offerId,
              scope.organizationId,
            );
      if (!isCurrentScope(scope)) return;
      updateOwnOffer(offer);
      setEditor(null);
    } catch (caught) {
      if (!isCurrentScope(scope)) return;
      if (caught instanceof ApiError && caught.status === 409) {
        await authoritativeRefresh(offerId, scope);
        if (!isCurrentScope(scope)) return;
        setError(
          "The offer changed. Its authoritative state was refreshed; the action was not retried.",
        );
      } else setError("The offer action failed. No action was retried.");
    } finally {
      releaseMutation(scope, token);
    }
  }

  const eligibleAircraft =
    aircraft?.filter((item) => item.eligible && item.status === "ACTIVE") ?? [];
  return (
    <div className="operator">
      <Container>
        <PageHeading
          title="Flight opportunities"
          description="Review eligible requests and manage your organization’s own offers."
        />
        {organizations.length > 1 ? (
          <label className="operator-org">
            Operator organization
            <select
              className="operator-org__select"
              value={organizationId}
              onChange={(event) => {
                resetScopedState(event.target.value);
                setOrganizationId(event.target.value);
              }}
            >
              <option value="">Choose operator organization</option>
              {organizations.map((org, index) => (
                <option key={org.id} value={org.id}>
                  Operator organization {index + 1} — {org.role}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {!organizationId ? (
          <EmptyState
            title="Choose operator organization"
            description="Select which operator marketplace you want to view."
          />
        ) : null}
        {organizationId ? (
          <div className="operator-market__toolbar">
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() => {
                setOpportunities(null);
                setAircraft(null);
                void load(organizationId);
              }}
            >
              Refresh marketplace
            </Button>
          </div>
        ) : null}
        {error ? (
          <Alert tone="error" title="Marketplace action needs attention">
            {error}
          </Alert>
        ) : null}
        {organizationId && (opportunities === null || aircraft === null) ? (
          <LoadingState label="Loading flight opportunities…" />
        ) : null}
        {opportunities?.length === 0 ? (
          <EmptyState
            title="No current opportunities"
            description="No submitted trip requests are currently available to this operator."
          />
        ) : null}
        {opportunities && opportunities.length > 0 ? (
          <div className="operator-market" aria-busy={busy}>
            {opportunities.map((opportunity) => (
              <Card
                as="article"
                className="operator-opportunity"
                key={opportunity.trip_request_id}
              >
                <header>
                  <div>
                    <p className="operator-opportunity__eyebrow">
                      Submitted opportunity
                    </p>
                    <h2>Flight request</h2>
                  </div>
                  <time dateTime={opportunity.created_at}>
                    {new Date(opportunity.created_at).toLocaleDateString(
                      "en-IE",
                    )}
                  </time>
                </header>
                <div className="operator-opportunity__legs">
                  {opportunity.legs.map((leg) => (
                    <section
                      key={leg.sequence}
                      aria-label={`Leg ${leg.sequence}`}
                    >
                      <strong>
                        {leg.origin_airport_code}{" "}
                        <span aria-hidden="true">→</span>{" "}
                        {leg.destination_airport_code}
                      </strong>
                      <span>
                        <time dateTime={leg.departure_at}>
                          {new Date(leg.departure_at).toLocaleString("en-IE")}
                        </time>
                      </span>
                      <span>
                        {leg.passenger_count}{" "}
                        {leg.passenger_count === 1 ? "passenger" : "passengers"}
                      </span>
                    </section>
                  ))}
                </div>
                <div className="operator-own-offers">
                  <h3>Your offers</h3>
                  {opportunity.own_offers.length === 0 ? (
                    <p>No offer created.</p>
                  ) : (
                    opportunity.own_offers.map((offer) => (
                      <div className="operator-own-offer" key={offer.offer_id}>
                        <span
                          className={`operator-status operator-status--${offer.status.toLowerCase()}`}
                        >
                          {offer.status}
                        </span>
                        {details[offer.offer_id] ? (
                          <span>
                            {formatOperatorMoney(
                              details[offer.offer_id].operator_amount_minor,
                              details[offer.offer_id].currency,
                            )}
                          </span>
                        ) : null}
                        {activeOrganization?.canManage &&
                        offer.status === "DRAFT" ? (
                          <>
                            <Button
                              variant="ghost"
                              disabled={busy}
                              onClick={() =>
                                void openDraft(
                                  opportunity.trip_request_id,
                                  offer.offer_id,
                                )
                              }
                            >
                              Edit draft
                            </Button>
                            <Button
                              disabled={busy}
                              onClick={() =>
                                void transition(offer.offer_id, "submit")
                              }
                            >
                              Submit offer
                            </Button>
                          </>
                        ) : null}
                        {activeOrganization?.canManage &&
                        offer.status === "SUBMITTED" ? (
                          <Button
                            variant="secondary"
                            disabled={busy}
                            onClick={() =>
                              void transition(offer.offer_id, "withdraw")
                            }
                          >
                            Withdraw offer
                          </Button>
                        ) : null}
                      </div>
                    ))
                  )}
                </div>
                {!activeOrganization?.canManage ? (
                  <p className="operator-opportunity__readonly">
                    Read-only access
                  </p>
                ) : opportunity.own_offers.some(
                    (offer) =>
                      offer.status === "DRAFT" ||
                      offer.status === "SUBMITTED" ||
                      offer.status === "SELECTED",
                  ) ? null : (
                  <Button
                    disabled={busy || eligibleAircraft.length === 0}
                    onClick={() => void openDraft(opportunity.trip_request_id)}
                  >
                    Create offer
                  </Button>
                )}
                {activeOrganization?.canManage &&
                eligibleAircraft.length === 0 ? (
                  <p className="operator-opportunity__hint">
                    No eligible active aircraft are available.
                  </p>
                ) : null}
                {editor?.tripId === opportunity.trip_request_id ? (
                  <form className="operator-offer-form" onSubmit={save}>
                    <h3>
                      {editor.offerId ? "Edit draft offer" : "Create offer"}
                    </h3>
                    {!editor.offerId ? (
                      <label>
                        Aircraft
                        <select
                          required
                          value={form.aircraftId}
                          onChange={(e) =>
                            setForm({ ...form, aircraftId: e.target.value })
                          }
                        >
                          <option value="">Choose eligible aircraft</option>
                          {eligibleAircraft.map((item) => (
                            <option key={item.id} value={item.id}>
                              {item.registration} — {item.manufacturer}{" "}
                              {item.model} ({item.passenger_capacity} seats)
                            </option>
                          ))}
                        </select>
                      </label>
                    ) : null}
                    <div className="operator-offer-form__money">
                      <label>
                        Currency
                        <select
                          value={form.currency}
                          onChange={(e) =>
                            setForm({
                              ...form,
                              currency: e.target.value as FormState["currency"],
                            })
                          }
                        >
                          <option>EUR</option>
                          <option>GBP</option>
                          <option>USD</option>
                        </select>
                      </label>
                      <label>
                        Operator amount
                        <input
                          required
                          inputMode="decimal"
                          value={form.operatorAmount}
                          onChange={(e) =>
                            setForm({ ...form, operatorAmount: e.target.value })
                          }
                        />
                      </label>
                      <label>
                        Tax amount
                        <input
                          required
                          inputMode="decimal"
                          value={form.taxAmount}
                          onChange={(e) =>
                            setForm({ ...form, taxAmount: e.target.value })
                          }
                        />
                      </label>
                    </div>
                    <label>
                      Valid until (required before submission)
                      <input
                        type="datetime-local"
                        value={form.validUntil}
                        onChange={(e) =>
                          setForm({ ...form, validUntil: e.target.value })
                        }
                      />
                    </label>
                    <label>
                      Operator notes (optional)
                      <textarea
                        maxLength={1000}
                        value={form.operatorNotes}
                        onChange={(e) =>
                          setForm({ ...form, operatorNotes: e.target.value })
                        }
                      />
                    </label>
                    <label>
                      Included services (optional)
                      <textarea
                        maxLength={2000}
                        value={form.includedServices}
                        onChange={(e) =>
                          setForm({ ...form, includedServices: e.target.value })
                        }
                      />
                    </label>
                    <label>
                      Excluded services (optional)
                      <textarea
                        maxLength={2000}
                        value={form.excludedServices}
                        onChange={(e) =>
                          setForm({ ...form, excludedServices: e.target.value })
                        }
                      />
                    </label>
                    <label>
                      Cancellation policy (optional)
                      <textarea
                        maxLength={1000}
                        value={form.cancellationPolicy}
                        onChange={(e) =>
                          setForm({
                            ...form,
                            cancellationPolicy: e.target.value,
                          })
                        }
                      />
                    </label>
                    <div className="operator-offer-form__actions">
                      <Button disabled={busy} type="submit">
                        Save draft
                      </Button>
                      <Button
                        variant="ghost"
                        type="button"
                        disabled={busy}
                        onClick={() => setEditor(null)}
                      >
                        Cancel
                      </Button>
                    </div>
                  </form>
                ) : null}
              </Card>
            ))}
          </div>
        ) : null}
      </Container>
    </div>
  );
}
