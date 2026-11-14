from fastapi.testclient import TestClient

from app.main import create_app


client = TestClient(create_app())


def test_health_endpoint_returns_ok():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["status"] == "healthy"
    assert body["service"]
    assert "timestamp" in body


def test_readiness_endpoint_reports_database_connectivity():
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "connected"
    assert body["checks"]["auth"] == "not_configured"
    assert "database" in body["note"].lower()


def test_readiness_endpoint_reports_database_failure(monkeypatch):
    """Database probe failure must yield HTTP 503 with a safe, generic error contract.

    The probe is mocked — no real unavailable database is required for this unit test.
    """
    from app.api.v1 import endpoints as endpoints_package
    from app.api.v1.endpoints import health as health_module

    def failing_probe() -> str:
        return "error"

    monkeypatch.setattr(health_module, "_database_check", failing_probe)
    # Some import styles could rebind the symbol onto the package; patch both defensively.
    monkeypatch.setattr(endpoints_package, "_database_check", failing_probe, raising=False)

    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["ok"] is False
    assert body["status"] == "not_ready"
    assert body["checks"]["database"] == "error"
    assert body["checks"]["auth"] == "not_configured"


def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["api"] == "/api/v1"


def test_consistent_error_shape_for_not_found():
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "HTTP_404"
    assert "message" in body["error"]
