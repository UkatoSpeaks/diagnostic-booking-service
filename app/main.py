from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.db.session import engine
from sqlalchemy import text


app = FastAPI(
    title="Diagnostic Booking Service",
    description="Backend service for diagnostic test bookings and simulated payments.",
    version="1.0.0",
)


app.include_router(auth_router)


@app.get("/health")
def health_check():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        return {
            "status": "healthy",
            "database": "connected",
        }

    except Exception:
        return {
            "status": "unhealthy",
            "database": "disconnected",
        }