import pytest
from jose import jwt

from app.core.config import settings


def test_signup_returns_token_and_me_works(client, signup):
    headers = signup("new@example.com")

    response = client.get("/auth/me", headers=headers)

    assert response.status_code == 200
    assert response.json()["email"] == "new@example.com"
    assert response.json()["is_admin"] is False


def test_signup_duplicate_email_conflicts_case_insensitively(client, signup):
    signup("dup@example.com")

    response = client.post(
        "/auth/signup",
        json={"name": "Dup", "email": "DUP@Example.com", "password": "password123"},
    )

    assert response.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "A", "email": "a@example.com", "password": "password123"},
        {"name": "Alice", "email": "not-an-email", "password": "password123"},
        {"name": "Alice", "email": "a@example.com", "password": "short"},
        {"email": "a@example.com", "password": "password123"},
    ],
)
def test_signup_validation(client, payload):
    assert client.post("/auth/signup", json=payload).status_code == 422


def test_login_success(client, signup):
    signup("login@example.com")

    response = client.post(
        "/auth/login",
        json={"email": "login@example.com", "password": "password123"},
    )

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"


@pytest.mark.parametrize(
    "email,password",
    [("login@example.com", "wrong-password"), ("nobody@example.com", "password123")],
)
def test_login_rejects_bad_credentials(client, signup, email, password):
    signup("login@example.com")

    response = client.post("/auth/login", json={"email": email, "password": password})

    assert response.status_code == 401


def test_protected_endpoint_requires_token(client):
    assert client.get("/auth/me").status_code in (401, 403)


def test_invalid_token_rejected(client):
    response = client.get("/auth/me", headers={"Authorization": "Bearer garbage"})

    assert response.status_code == 401


def test_expired_token_rejected(client, signup):
    signup("exp@example.com")
    token = jwt.encode(
        {"sub": "1", "exp": 1},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_admin_flag_set_for_configured_email(client, admin_headers):
    assert client.get("/auth/me", headers=admin_headers).json()["is_admin"] is True


def test_login_is_rate_limited(client, signup):
    from app.core.rate_limit import limiter

    signup("rate@example.com")
    limiter.enabled = True
    limiter.reset()
    try:
        codes = [
            client.post(
                "/auth/login",
                json={"email": "rate@example.com", "password": "wrong-password"},
            ).status_code
            for _ in range(12)
        ]
    finally:
        limiter.enabled = False
        limiter.reset()

    assert codes[0] == 401
    assert codes[-1] == 429
