import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from app.api.auth import router as auth_router
from app.api.bookings import router as booking_router
from app.api.catalog import router as catalog_router
from app.api.payments import router as payment_router
from app.core.logging import configure_logging, request_id_var
from app.core.rate_limit import limiter
from app.db.session import engine

configure_logging()
logger = logging.getLogger("app.request")

app = FastAPI(
    title="Diagnostic Booking Service",
    description="Backend service for diagnostic test bookings and simulated payments.",
    version="1.0.0",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    request_id_var.set(request_id)
    started = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        logger.exception("unhandled error %s %s", request.method, request.url.path)
        response = JSONResponse(
            status_code=500, content={"detail": "Internal server error"}
        )

    response.headers["X-Request-ID"] = request_id
    logger.info(
        "%s %s -> %s (%.1f ms)",
        request.method,
        request.url.path,
        response.status_code,
        (time.perf_counter() - started) * 1000,
    )
    return response


app.include_router(auth_router)
app.include_router(catalog_router)
app.include_router(booking_router)
app.include_router(payment_router)


@app.get("/health", tags=["Health"])
def health_check():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        logger.exception("health check failed")
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "database": "disconnected"},
        )

    return {"status": "healthy", "database": "connected"}
