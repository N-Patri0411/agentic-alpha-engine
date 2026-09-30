"""Bounded handlers used by the standalone local worker."""

from __future__ import annotations

from alpha_workbench.persistence import ProductRepository

from .dispatch import Handler, JobContext


def workspace_bootstrap_handler(workspace_repository: ProductRepository) -> Handler:
    """Build the deterministic demo bootstrap handler used by the local API."""

    def run(context: JobContext) -> None:
        workspace_id = str(context.payload.get("workspace_id", ""))
        if not workspace_id:
            raise ValueError("workspace-bootstrap requires workspace_id")
        workspace = workspace_repository.latest_workspace(workspace_id)
        for value, message in (
            (0.25, "workspace validated"),
            (0.50, "runtime dependencies checked"),
            (0.75, "bootstrap artifacts prepared"),
        ):
            context.progress(value, message, event_key=f"{context.job_id}:bootstrap:{value:.2f}")
        workspace_repository.put(
            workspace.model_copy(update={"version": workspace.version + 1, "status": "ready"})
        )

    return run
