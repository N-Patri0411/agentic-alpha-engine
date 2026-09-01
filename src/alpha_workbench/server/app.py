"""FastAPI skeleton for local run status and future evidence review."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from ..agents.contracts import AgentRun

app = FastAPI(title="Agentic Alpha Workbench", version="0.1.0")
_runs: dict[str, AgentRun] = {}


class StartRunRequest(BaseModel):
    name: str


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "scope": "local-only skeleton"}


@app.post("/api/runs", status_code=201)
def start_run(request: StartRunRequest) -> AgentRun:
    run = AgentRun(id=str(uuid4()), created_at=datetime.now(UTC))
    _runs[run.id] = run
    return run


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> AgentRun:
    try:
        return _runs[run_id]
    except KeyError as error:
        raise HTTPException(status_code=404, detail="run not found") from error


@app.get("/api/proposals")
def list_proposals() -> list[object]:
    """Phase 2 will replace this placeholder with evidence-backed proposals."""

    return []
