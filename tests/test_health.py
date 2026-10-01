from uuid import UUID

from fastapi.testclient import TestClient

from api.app import app


def test_health_returns_ok_and_request_id() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    UUID(response.headers["X-Request-ID"])


def test_valid_request_id_is_preserved() -> None:
    request_id = "ec245ae3-754f-4c64-8dd6-8b54eef9903f"
    with TestClient(app) as client:
        response = client.get("/ready", headers={"X-Request-ID": request_id})

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"app": "ok", "config": "ok"},
    }
    assert response.headers["X-Request-ID"] == request_id


def test_invalid_request_id_is_replaced() -> None:
    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Request-ID": "not-a-uuid"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "not-a-uuid"
    UUID(response.headers["X-Request-ID"])
