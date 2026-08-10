import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from sky_bridge_jet.api.router import api_v1_router
from sky_bridge_jet.core.config import get_settings
from sky_bridge_jet.core.logging import configure_logging
from sky_bridge_jet.db.session import get_db
from sky_bridge_jet.modules.core_aviation.router import register_exception_handlers
from sky_bridge_jet.modules.core_aviation.schemas import ErrorResponse

configure_logging(get_settings().log_level)
logger = logging.getLogger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach an opaque correlation ID and low-risk response hardening headers."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        correlation_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.correlation_id = correlation_id
        started_at = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = correlation_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        logger.info(
            "request_completed",
            extra={
                "correlation_id": correlation_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
            },
        )
        return response


app = FastAPI(
    title="Sky Bridge Jet API",
    version="0.1.0",
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse}},
)
app.add_middleware(RequestContextMiddleware)
register_exception_handlers(app)
app.include_router(api_v1_router)
DatabaseSession = Annotated[Session, Depends(get_db)]


@app.get("/health", tags=["platform"])
def health() -> dict[str, str]:
    """Return process health without requiring a database connection."""
    return {"status": "ok"}


@app.get("/ready", tags=["platform"])
def ready(session: DatabaseSession) -> dict[str, str]:
    """Return readiness only when PostgreSQL accepts a lightweight query."""
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.warning("database_unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "unavailable"},
        ) from None
    return {"status": "ok"}


@app.get("/api/v1", tags=["platform"])
def api_v1_root() -> dict[str, str]:
    """Expose the versioned API namespace without adding business endpoints."""
    return {"status": "ok", "version": "v1"}
