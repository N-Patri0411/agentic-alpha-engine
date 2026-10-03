import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "../src/App";

vi.mock("cytoscape", () => ({
  default: vi.fn(() => ({
    on: vi.fn(),
    destroy: vi.fn(),
    $id: vi.fn(() => ({ select: vi.fn() })),
  })),
}));

const workspace = {
  workspace_id: "w-graph", name: "Chip supply chain", domain: "Semiconductors",
  base_currency: "USD", cadence: "daily", regions: ["US", "TW"],
  universe_id: "u-graph", graph_version_id: null, status: "ready",
  provider_ids: [], version: 2, created_at: "2026-10-01T12:00:00Z",
};
const nodes = [
  ...Array.from({ length: 10 }, (_, index) => ({
    node_id: `inst-${index}`, node_kind: "company", label: ["NVDA", "TSMC", "AMD", "ASML", "Samsung", "Micron", "Intel", "GFS", "AMAT", "LRCX"][index],
    tradeable: true, instrument_id: `instrument-${index}`, metadata: {},
  })),
  { node_id: "ctx-demand", node_kind: "demand_context", label: "AI demand", tradeable: false, entity_id: "demand", metadata: {} },
];
const relationships = [
  { relationship_id: "r-1", source_node_id: "inst-0", target_node_id: "inst-1", relationship_type: "manufacturing_dependency", direction: "forward" },
  { relationship_id: "r-2", source_node_id: "ctx-demand", target_node_id: "inst-0", relationship_type: "demand_exposure", direction: "forward" },
];
const snapshot = (snapshotId: string, asOf: string) => ({
  snapshot_id: snapshotId, workspace_id: workspace.workspace_id, universe_id: "u-graph",
  as_of_time: asOf, created_at: asOf, nodes, relationships,
  states: relationships.map((relation, index) => ({
    relationship_id: relation.relationship_id, confidence: index ? 0.78 : 0.92,
    economic_exposure: index ? 0.55 : 0.84, propagation_coefficient: index ? 0.21 : 0.68,
    freshness: 0.91, strategy_eligible: !index, lifecycle_status: index ? "candidate" : "active",
    evidence_ids: [`ev-${index}-a`, `ev-${index}-b`],
  })),
  coverage: { tradeable_connected: 9, total_tradeable: 10, eligible_relationships: 1, total_relationships: 2, freshness: 0.91 },
});
const summaries = [
  { snapshot_id: "snap-1", workspace_id: workspace.workspace_id, as_of_time: "2026-09-30T10:00:00Z", created_at: "2026-09-30T10:00:00Z" },
  { snapshot_id: "snap-2", workspace_id: workspace.workspace_id, as_of_time: "2026-10-01T12:00:00Z", created_at: "2026-10-01T12:00:00Z" },
];

function json(value: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } }));
}
function mockGraphApi({ noWorkspace = false, graphError = false } = {}) {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path === "/api/health") return json({ status: "ok" });
    if (path === "/api/workspaces") return json(noWorkspace ? [] : [workspace]);
    if (path === "/api/jobs") return json([]);
    if (path.startsWith("/api/workspaces/w-graph/graph/snapshots")) return graphError ? json({ detail: "Graph service unavailable" }, 503) : json(summaries);
    if (path.startsWith("/api/graph-snapshots/snap-1/diff")) return json({ added: [{ relationship_id: "new-r", label: "new relationship" }], removed: [], changed: [{ relationship_id: "r-1", label: "confidence updated" }] });
    if (path.startsWith("/api/graph-snapshots/snap-1")) return json(snapshot("snap-1", summaries[0].as_of_time));
    if (path.startsWith("/api/graph-snapshots/snap-2/diff")) return json({ added: [{ relationship_id: "r-2", label: "Added demand exposure" }], removed: [{ relationship_id: "old-r", label: "Removed relationship" }], changed: [{ relationship_id: "r-1", label: "Confidence updated" }] });
    if (path.startsWith("/api/graph-snapshots/snap-2")) return json(snapshot("snap-2", summaries[1].as_of_time));
    if (path === "/api/workspaces/w-graph/graph-refresh" && init?.method === "POST") return json({ id: "j-refresh", kind: "graph-refresh", status: "queued", created_at: "2026-10-01T13:00:00Z", started_at: null, finished_at: null, progress: 0, message: "Queued", cancel_requested: false }, 202);
    return json({ detail: "not found" }, 404);
  }));
}
function renderGraph() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={["/graph"]}><App /></MemoryRouter></QueryClientProvider>);
}

afterEach(() => { vi.unstubAllGlobals(); });

test("shows coverage, external context, snapshot slider and added/removed/changed diff", async () => {
  mockGraphApi();
  const user = userEvent.setup();
  renderGraph();
  expect(await screen.findByRole("heading", { name: "Evidence graph" })).toBeInTheDocument();
  expect(await screen.findByText("9 / 10")).toBeInTheDocument();
  expect(screen.getByText("AI demand · context")).toBeInTheDocument();
  expect(screen.getByText("NVDA · instrument")).toBeInTheDocument();
  expect(screen.getByRole("slider", { name: "Select graph snapshot" })).toHaveAttribute("max", "1");
  expect(await screen.findByText("Added demand exposure")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("slider", { name: "Select graph snapshot" }), { target: { value: "0" } });
  expect(await screen.findByText("confidence updated")).toBeInTheDocument();
});

test("switches economic/statistical layers and applies relationship filters", async () => {
  mockGraphApi();
  const user = userEvent.setup();
  renderGraph();
  expect(await screen.findByText((_text, element) => element?.textContent === "NVDA → TSMC")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Statistical layer" }));
  expect(screen.getByRole("heading", { name: "Statistical propagation" })).toBeInTheDocument();
  await user.click(screen.getByLabelText("Manufacturing Dependency"));
  await user.click(screen.getByLabelText("Demand Exposure"));
  expect(screen.getByText("No relationships match these filters.")).toBeInTheDocument();
});

test("opens evidence drawer for a selected relationship", async () => {
  mockGraphApi();
  const user = userEvent.setup();
  renderGraph();
  await user.click(await screen.findByRole("button", { name: /NVDA TSMC Manufacturing Dependency/i }));
  expect(await screen.findByRole("dialog", { name: "NVDA → TSMC" })).toBeInTheDocument();
  expect(screen.getByText("Propagation coefficient")).toBeInTheDocument();
  expect(screen.getByText("ev-0-a")).toBeInTheDocument();
  expect(screen.getByText("Eligible for strategies")).toBeInTheDocument();
});

test("offers onboarding without a workspace and exposes graph API failures", async () => {
  mockGraphApi({ noWorkspace: true });
  renderGraph();
  expect(await screen.findByRole("heading", { name: "Start with a domain and locked universe" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /create a domain/i })).toHaveAttribute("href", "/new-domain");

  mockGraphApi({ graphError: true });
  renderGraph();
  expect(await screen.findByRole("alert")).toHaveTextContent("Graph service unavailable");
});

test("is accessible and responsive at a 1024px viewport", async () => {
  mockGraphApi();
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 1024 });
  const { container } = renderGraph();
  await screen.findByRole("heading", { name: "Evidence graph" });
  expect(await screen.findByRole("heading", { name: "Relationships" })).toBeInTheDocument();
  expect((await axe(container)).violations).toEqual([]);
});
