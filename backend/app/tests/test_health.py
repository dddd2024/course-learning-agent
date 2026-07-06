"""Tests for the health check endpoint."""


def test_health_returns_ok(client) -> None:
    """GET /api/v1/health should return 200 with body {"status": "ok"}."""
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
