import type { Job, Workspace } from "./api";

export const demoWorkspace: Workspace = {
  workspace_id: "demo-semiconductor-core", name: "Semiconductor Core",
  domain: "Global semiconductor supply chain", base_currency: "USD", cadence: "daily",
  regions: ["US", "TW", "NL", "KR"], universe_id: "demo-universe-v1",
  graph_version_id: "demo-graph-v4", status: "ready", provider_ids: [], version: 4,
  created_at: "2026-09-30T13:00:00Z",
};

export const demoJobs: Job[] = [
  { id: "demo-job-graph", kind: "graph-refresh", status: "running", created_at: "2026-09-30T14:32:00Z", started_at: "2026-09-30T14:32:03Z", finished_at: null, progress: 0.68, message: "Scoring relationship evidence", cancel_requested: false },
  { id: "demo-job-backtest", kind: "strategy-backtest", status: "queued", created_at: "2026-09-30T14:41:00Z", started_at: null, finished_at: null, progress: 0, message: "Waiting for graph snapshot", cancel_requested: false },
];

export const demoEntities = ["NVIDIA", "AMD", "TSMC", "ASML", "Samsung", "Micron", "Intel", "GlobalFoundries", "Applied Materials", "Lam Research"];
export const demoSignals = [
  { name: "Capacity ripple", score: "+0.31", state: "Validated", health: 92 },
  { name: "Foundry concentration", score: "+0.18", state: "Testing", health: 68 },
  { name: "Supplier stress", score: "−0.07", state: "Paused", health: 41 },
] as const;
