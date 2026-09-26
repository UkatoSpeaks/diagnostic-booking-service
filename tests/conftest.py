import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parent.parent


def _test_database_url() -> str:
    url = os.getenv("TEST_DATABASE_URL")

    if not url:
        base = os.getenv("DATABASE_URL") or dotenv_values(ROOT / ".env").get(
            "DATABASE_URL"
        )
        if not base:
            raise RuntimeError("Set TEST_DATABASE_URL (or DATABASE_URL) to run tests")

        parsed = make_url(base)
        name = parsed.database
        if not name.endswith("_test"):
            name = f"{name}_test"
        url = parsed.set(database=name).render_as_string(hide_password=False)

    # The suite drops and truncates tables, so never let it touch a real DB.
    if not make_url(url).database.endswith("_test"):
        raise RuntimeError("Test database name must end with '_test'")

    return url


# Must happen before the app (and its settings/engine) is imported.
TEST_DATABASE_URL = _test_database_url()
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["SECRET_KEY"] = "test-secret-key-used-only-by-pytest"
os.environ["WEBHOOK_SECRET"] = "test-webhook-secret"
os.environ["ADMIN_EMAILS"] = "admin@example.com"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.rate_limit import limiter  # noqa: E402
from app.db.session import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.payments import sign_payload  # noqa: E402

limiter.enabled = False


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables():
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def signup(client):
    def _signup(email: str) -> dict:
        response = client.post(
            "/auth/signup",
            json={"name": "Test User", "email": email, "password": "password123"},
        )
        assert response.status_code == 201, response.text
        return _headers(response.json()["access_token"])

    return _signup


@pytest.fixture
def user_headers(signup):
    return signup("user@example.com")


@pytest.fixture
def other_headers(signup):
    return signup("other@example.com")


@pytest.fixture
def admin_headers(signup):
    return signup("admin@example.com")


@pytest.fixture
def catalog(client, admin_headers):
    """A centre offering one test priced at 500."""
    centre = client.post(
        "/catalog/centres",
        headers=admin_headers,
        json={"name": "City Diagnostics", "location": "Dehradun"},
    ).json()
    test = client.post(
        "/catalog/tests",
        headers=admin_headers,
        json={"name": "CBC Test", "description": "Complete Blood Count"},
    ).json()
    mapping = client.post(
        "/catalog/centre-tests",
        headers=admin_headers,
        json={"centre_id": centre["id"], "test_id": test["id"], "price": 500},
    ).json()
    return {
        "centre_id": centre["id"],
        "test_id": test["id"],
        "centre_test_id": mapping["id"],
        "price": 500,
    }


@pytest.fixture
def make_booking(client, catalog):
    def _make(headers: dict) -> dict:
        response = client.post(
            "/bookings/",
            headers=headers,
            json={
                "test_id": catalog["test_id"],
                "centre_id": catalog["centre_id"],
                "appointment_at": (
                    datetime.now(timezone.utc) + timedelta(days=1)
                ).isoformat(),
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    return _make


@pytest.fixture
def booking(make_booking, user_headers):
    return make_booking(user_headers)


@pytest.fixture
def post_webhook(client):
    """POST a signed webhook. Pass signature=None to omit the header."""

    def _post(payload: dict, signature="valid"):
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}

        if signature == "valid":
            headers["X-Signature"] = sign_payload(body)
        elif signature is not None:
            headers["X-Signature"] = signature

        return client.post("/payments/webhook/", content=body, headers=headers)

    return _post


@pytest.fixture
def get_booking(client):
    def _get(booking_id: int, headers: dict) -> dict:
        return client.get(f"/bookings/{booking_id}", headers=headers).json()

    return _get
