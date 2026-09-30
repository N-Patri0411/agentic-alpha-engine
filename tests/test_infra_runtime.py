from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_compose_is_local_only_and_migrations_gate_runtime_services() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    published_ports = [
        line.strip() for line in compose.splitlines() if line.strip().startswith('- "127.0.0.1:')
    ]
    assert len(published_ports) == 4
    assert all('"127.0.0.1:' in line for line in published_ports)
    assert "condition: service_completed_successfully" in compose
    assert compose.count("condition: service_completed_successfully") == 2
    assert "--appendonly" in compose
    assert "./web:/app/web" in compose
    assert "VITE_API_BASE_URL: http://api:8000" in compose
    assert "VITE_API_BASE_URL: http://127.0.0.1" not in compose
    assert "http://127.0.0.1:8000/api/readiness" in compose
    assert "http://127.0.0.1:8000/api/health" not in compose


def test_starter_waits_for_health_and_compose_uses_locked_web_install() -> None:
    starter = (ROOT / "scripts" / "start-studio.ps1").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert '"--wait"' in starter
    assert "npm ci" in compose
    assert (ROOT / "web" / "package-lock.json").is_file()
