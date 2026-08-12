from fastapi import APIRouter

from sky_bridge_jet.modules.bookings.router import router as bookings_router
from sky_bridge_jet.modules.compliance.router import router as compliance_router
from sky_bridge_jet.modules.core_aviation.router import router as core_aviation_router
from sky_bridge_jet.modules.offers.router import router as offers_router
from sky_bridge_jet.modules.payments.router import router as payments_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(core_aviation_router)
api_v1_router.include_router(offers_router)
api_v1_router.include_router(bookings_router)
api_v1_router.include_router(payments_router)
api_v1_router.include_router(compliance_router)
