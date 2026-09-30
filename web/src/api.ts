export type ApiHealth = { status: string; scope?: string; runtime?: Record<string, string> };

export type Workspace = {
  workspace_id: string; name: string; domain: string; base_currency: string;
  cadence: "daily" | "weekly" | "monthly"; regions: string[];
  universe_id: string | null; graph_version_id: string | null;
  status: "draft" | "building" | "ready" | "degraded" | "archived";
  provider_ids: string[]; version: number; created_at: string;
};

export type WorkspaceCreate = Pick<Workspace, "name" | "domain" | "cadence"> & {
  base_currency: string; regions: string[]; status: "draft" | "building";
};

export type Job = {
  id: string; kind: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  created_at: string; started_at: string | null; finished_at: string | null;
  progress: number; message: string | null; cancel_requested: boolean;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<ApiHealth>("/api/health"),
  workspaces: () => request<Workspace[]>("/api/workspaces"),
  createWorkspace: (input: WorkspaceCreate) => request<Workspace>("/api/workspaces", { method: "POST", body: JSON.stringify(input) }),
  jobs: () => request<Job[]>("/api/jobs"),
  bootstrapWorkspace: (workspaceId: string) => request<Job>("/api/jobs", { method: "POST", body: JSON.stringify({ kind: "workspace-bootstrap", idempotency_key: `workspace-bootstrap:${workspaceId}`, payload: { workspace_id: workspaceId } }) }),
};
