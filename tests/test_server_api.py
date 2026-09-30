from fastapi.testclient import TestClient

from alpha_workbench.product import DomainWorkspace
from alpha_workbench.server.app import create_app, make_in_memory_dependencies


def client() -> TestClient:
    return TestClient(create_app(make_in_memory_dependencies()))


def test_workspace_persists_and_health_is_local_without_secret_values() -> None:
    api = client()
    created = api.post(
        "/api/workspaces",
        json={
            "workspace_id": "w-semis",
            "name": "Semiconductor basket",
            "domain": "semiconductor manufacturing",
            "provider_ids": ["eodhd-secret-token-name"],
        },
    )
    assert created.status_code == 201
    assert api.get("/api/workspaces/w-semis").json()["domain"] == "semiconductor manufacturing"
    assert api.get("/api/workspaces").json()[0]["workspace_id"] == "w-semis"

    health = api.get("/api/health")
    assert health.status_code == 200
    assert health.json()["scope"] == "local-only"
    assert "secret-token" not in health.text
    assert api.get("/api/readiness").json()["status"] == "ready"


def test_workspace_listing_uses_latest_versions_in_deterministic_order() -> None:
    dependencies = make_in_memory_dependencies()
    dependencies.workspace_repository.put(
        DomainWorkspace(workspace_id="z-last", name="Old", domain="semiconductors")
    )
    dependencies.workspace_repository.put(
        DomainWorkspace(
            workspace_id="z-last",
            name="New",
            domain="semiconductors",
            version=2,
        )
    )
    dependencies.workspace_repository.put(
        DomainWorkspace(workspace_id="a-first", name="First", domain="energy")
    )
    api = TestClient(create_app(dependencies))

    listed = api.get("/api/workspaces").json()
    assert [(item["workspace_id"], item["version"]) for item in listed] == [
        ("a-first", 1),
        ("z-last", 2),
    ]
    assert api.get("/api/workspaces/z-last").json()["name"] == "New"


def test_readiness_failure_is_503_and_redacts_probe_secrets() -> None:
    dependencies = make_in_memory_dependencies()

    def failing_probe() -> bool:
        raise RuntimeError("postgresql://user:top-secret@localhost/alpha")

    dependencies.readiness_probes = (("postgres", failing_probe), ("redis", lambda: True))
    response = TestClient(create_app(dependencies)).get("/api/readiness")

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "checks": [
            {"name": "postgres", "status": "fail", "detail": "RuntimeError"},
            {"name": "redis", "status": "pass", "detail": "ready"},
        ],
    }
    assert "top-secret" not in response.text
    assert "postgresql://" not in response.text


def test_duplicate_bootstrap_is_idempotent_and_progress_is_pollable() -> None:
    api = client()
    api.post(
        "/api/workspaces",
        json={"workspace_id": "w-1", "name": "Semis", "domain": "semiconductors"},
    )
    request = {
        "kind": "workspace-bootstrap",
        "idempotency_key": "bootstrap-w-1",
        "payload": {"workspace_id": "w-1"},
    }
    first = api.post("/api/jobs", json=request)
    second = api.post("/api/jobs", json=request)
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    job_id = first.json()["id"]
    assert api.get(f"/api/jobs/{job_id}").json()["status"] == "succeeded"
    assert [job["id"] for job in api.get("/api/jobs").json()] == [job_id]
    events = api.get(f"/api/jobs/{job_id}/events").json()
    assert len(events) == 6
    assert [event["event_type"] for event in events] == [
        "queued",
        "started",
        "progress",
        "progress",
        "progress",
        "completed",
    ]
    assert api.get("/api/workspaces/w-1").json()["status"] == "ready"


def test_queued_job_can_be_cancelled_and_events_remain_private() -> None:
    api = client()
    response = api.post(
        "/api/jobs",
        json={
            "kind": "future-job",
            "idempotency_key": "future-1",
            "payload": {"credential": "must-not-appear"},
        },
    )
    assert response.status_code == 202
    job_id = response.json()["id"]
    cancelled = api.post(f"/api/jobs/{job_id}/cancel")
    assert cancelled.json()["cancel_requested"] is True
    assert api.get(f"/api/jobs/{job_id}").json()["status"] == "queued"
    assert "must-not-appear" not in api.get(f"/api/jobs/{job_id}").text
    assert "must-not-appear" not in api.get(f"/api/jobs/{job_id}/events").text
