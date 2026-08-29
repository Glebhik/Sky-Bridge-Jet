from fastapi import APIRouter, Depends

from sky_bridge_jet.modules.bookings.router import router as bookings_router
from sky_bridge_jet.modules.compliance.router import router as compliance_router
from sky_bridge_jet.modules.core_aviation.router import router as core_aviation_router
from sky_bridge_jet.modules.customer_reads import router as customer_reads_router
from sky_bridge_jet.modules.financials.router import router as financials_router
from sky_bridge_jet.modules.flight_operations.router import router as flight_operations_router
from sky_bridge_jet.modules.iam.dependencies import enforce_authentication
from sky_bridge_jet.modules.iam.router import router as iam_router
from sky_bridge_jet.modules.offers.router import router as offers_router
from sky_bridge_jet.modules.operational_diagnostics import router as operational_diagnostics_router
from sky_bridge_jet.modules.payments.router import router as payments_router
from sky_bridge_jet.modules.pilot_governance.router import router as pilot_governance_router

# The global authentication gate: applied to the whole versioned router so every
# route is authenticated unless explicitly classified PUBLIC (fail closed). This is
# a dependency (not middleware) so it shares the request session and honors test
# ``dependency_overrides``.
api_v1_router = APIRouter(prefix="/api/v1", dependencies=[Depends(enforce_authentication)])
api_v1_router.include_router(iam_router)
api_v1_router.include_router(core_aviation_router)
api_v1_router.include_router(offers_router)
api_v1_router.include_router(bookings_router)
api_v1_router.include_router(payments_router)
api_v1_router.include_router(compliance_router)
api_v1_router.include_router(financials_router)
api_v1_router.include_router(flight_operations_router)
api_v1_router.include_router(customer_reads_router)
api_v1_router.include_router(pilot_governance_router)
api_v1_router.include_router(operational_diagnostics_router)
