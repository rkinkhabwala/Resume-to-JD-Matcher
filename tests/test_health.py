import time
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


def test_async_analysis_submission_returns_accepted_status() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/analyses",
            data={"job_text": "Senior Python engineer with SQL and AWS."},
            files={
                "resume_file": (
                    "resume.txt",
                    "Python, SQL, AWS, five years.",
                    "text/plain",
                )
            },
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    assert "analysis_id" in payload
    assert payload["status_url"].endswith(f"/api/v1/analyses/{payload['analysis_id']}")


def test_analysis_status_poll_tracks_completion() -> None:
    with TestClient(app) as client:
        submission = client.post(
            "/api/v1/analyses",
            data={"job_text": "Senior Python engineer with SQL and AWS."},
            files={
                "resume_file": (
                    "resume.txt",
                    "Python, SQL, AWS, five years.",
                    "text/plain",
                )
            },
        )

        analysis_id = submission.json()["analysis_id"]
        final_response = None
        for _ in range(50):
            final_response = client.get(f"/api/v1/analyses/{analysis_id}")
            if final_response.json()["status"] == "completed":
                break
            time.sleep(0.05)

    assert final_response is not None
    payload = final_response.json()
    assert payload["status"] == "completed"
    result = payload["result"]
    assert result["score"] >= 0
    assert result["confidence"]["label"] in {"Low", "Medium", "High"}
