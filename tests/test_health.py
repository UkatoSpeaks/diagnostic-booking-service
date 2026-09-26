from unittest.mock import patch


def test_health_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["database"] == "connected"
    assert "X-Request-ID" in response.headers


def test_health_returns_503_when_database_down(client):
    with patch("app.main.engine.connect", side_effect=RuntimeError("db down")):
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"
