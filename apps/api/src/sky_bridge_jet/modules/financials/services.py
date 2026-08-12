from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sky_bridge_jet.core.config import Settings, get_settings
from sky_bridge_jet.modules.core_aviation.domain import ResourceNotFoundError
from sky_bridge_jet.modules.core_aviation.repositories import OperatorRepository
from sky_bridge_jet.modules.financials.domain import (
    ConnectedAccountConflictError,
    FinancialEligibilityDecision,
    ProviderAccountSnapshot,
    compute_financial_eligibility,
    derive_onboarding_status,
)
from sky_bridge_jet.modules.financials.models import OperatorConnectedAccount
from sky_bridge_jet.modules.financials.provider import (
    FinancialConnectProvider,
    OnboardingLink,
    get_financial_connect_provider,
)
from sky_bridge_jet.modules.financials.repositories import OperatorConnectedAccountRepository
from sky_bridge_jet.modules.payments.domain import PaymentProviderKind


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _not_found(resource_name: str) -> ResourceNotFoundError:
    return ResourceNotFoundError(f"{resource_name} was not found")


def _apply_snapshot(account: OperatorConnectedAccount, snapshot: ProviderAccountSnapshot) -> None:
    account.charges_enabled = snapshot.charges_enabled
    account.payouts_enabled = snapshot.payouts_enabled
    account.requirements_due = snapshot.requirements_due
    account.disabled_reason = snapshot.disabled_reason
    account.onboarding_status = derive_onboarding_status(snapshot)
    account.synchronized_at = _utc_now()


def evaluate_financial_eligibility(
    session: Session, operator_id: UUID, provider: PaymentProviderKind
) -> FinancialEligibilityDecision:
    """Read-only financial eligibility for the payment gate (no provider call)."""
    account = OperatorConnectedAccountRepository(session).get(operator_id, provider)
    if account is None:
        return compute_financial_eligibility(
            status=None, charges_enabled=False, payouts_enabled=False, requirements_due=True
        )
    return compute_financial_eligibility(
        status=account.onboarding_status,
        charges_enabled=account.charges_enabled,
        payouts_enabled=account.payouts_enabled,
        requirements_due=account.requirements_due,
    )


class FinancialOnboardingService:
    """Operator financial onboarding via a provider-neutral connect port.

    Authorization is deferred; access is scoped by the operator id in the request,
    and the connected-account relationship must match that operator (no operator
    can reach another operator's onboarding state). Sky Bridge Jet does not collect
    KYC/KYB documents — the provider hosts onboarding and reports capability state.
    """

    def __init__(
        self,
        session: Session,
        connect_provider: FinancialConnectProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.provider = connect_provider or get_financial_connect_provider(self.settings)
        self.provider_kind: PaymentProviderKind = self.provider.kind
        self.accounts = OperatorConnectedAccountRepository(session)
        self.operators = OperatorRepository(session)

    def create_account(self, operator_id: UUID) -> OperatorConnectedAccount:
        try:
            with self.session.begin():
                if self.operators.get(operator_id) is None:
                    raise _not_found("Operator")
                existing = self.accounts.get(operator_id, self.provider_kind)
                if existing is not None:
                    raise ConnectedAccountConflictError(
                        "A connected account already exists for this operator"
                    )
                creation = self.provider.create_account(
                    country=self.settings.stripe_account_country, idempotency_key=str(operator_id)
                )
                account = self.accounts.add(
                    OperatorConnectedAccount(
                        operator_id=operator_id,
                        payment_provider=self.provider_kind.value,
                        provider_account_reference=creation.account_reference,
                        onboarding_status=derive_onboarding_status(creation.snapshot),
                        charges_enabled=creation.snapshot.charges_enabled,
                        payouts_enabled=creation.snapshot.payouts_enabled,
                        requirements_due=creation.snapshot.requirements_due,
                        account_country=creation.country,
                        disabled_reason=creation.snapshot.disabled_reason,
                        synchronized_at=_utc_now(),
                    )
                )
                self.session.flush()
                return account
        except IntegrityError as error:
            # A concurrent create lost the unique-constraint race; surface the same
            # domain conflict as the pre-check rather than a raw database error.
            raise ConnectedAccountConflictError(
                "A connected account already exists for this operator"
            ) from error

    def get_account(self, operator_id: UUID) -> OperatorConnectedAccount:
        account = self.accounts.get(operator_id, self.provider_kind)
        if account is None:
            raise _not_found("Connected account")
        return account

    def create_onboarding_link(self, operator_id: UUID) -> OnboardingLink:
        account = self.get_account(operator_id)
        # Ownership: the account was fetched by this operator id, so the link is
        # only ever issued for the operator's own account.
        return self.provider.create_onboarding_link(
            account_reference=account.provider_account_reference
        )

    def synchronize(self, operator_id: UUID) -> OperatorConnectedAccount:
        with self.session.begin():
            account = self.accounts.get_for_update(operator_id, self.provider_kind)
            if account is None:
                raise _not_found("Connected account")
            snapshot = self.provider.retrieve_account(
                account_reference=account.provider_account_reference
            )
            _apply_snapshot(account, snapshot)
            self.session.flush()
            return account

    def eligibility(self, operator_id: UUID) -> FinancialEligibilityDecision:
        if self.operators.get(operator_id) is None:
            raise _not_found("Operator")
        return evaluate_financial_eligibility(self.session, operator_id, self.provider_kind)
