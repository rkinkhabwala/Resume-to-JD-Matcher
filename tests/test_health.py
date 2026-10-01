import time
from dataclasses import dataclass
from uuid import UUID

from fastapi.testclient import TestClient

from api.app import app


@dataclass
class _FakeFetchedJob:
    title: str | None
    text: str
    source: str
    url: str


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


def test_extract_job_endpoint_returns_extracted_text(monkeypatch) -> None:
    def _fake_fetch(self, url: str):
        assert url == "https://example.com/job"
        return _FakeFetchedJob(
            title="Senior Python Engineer",
            text="Build Python services with SQL and AWS.",
            source="json_ld",
            url=url,
        )

    monkeypatch.setattr("api.app.JobFetcher.fetch", _fake_fetch)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/extract-job",
            json={"url": "https://example.com/job"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "Senior Python Engineer"
    assert payload["text"].startswith("Build Python")
    assert payload["source"] == "json_ld"
    assert payload["url"] == "https://example.com/job"


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
