import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { AlphaStudio } from "../src/AlphaStudio";
import { normalizeFeatureRefreshReceipt, pollFeatureRefreshJob } from "../src/api";

vi.mock("@monaco-editor/react", () => ({ default: ({ value, onChange, options }: { value: string; onChange: (value: string) => void; options: { ariaLabel: string } }) => <textarea aria-label={options.ariaLabel} value={value} onChange={(event) => onChange(event.target.value)} /> }));
vi.mock("../src/PythonEditor", () => ({ default: ({ value, onChange }: { value: string; onChange: (value: string) => void }) => <textarea aria-label="Python extension source" value={value} onChange={(event) => onChange(event.target.value)} /> }));

const workspace = { workspace_id: "w-live", name: "Energy Transition", domain: "energy", base_currency: "USD", cadence: "daily" as const, regions: ["US"], universe_id: "u-live", graph_version_id: "g-live", status: "ready" as const, provider_ids: [], version: 1, created_at: "2026-10-01T12:00:00Z" };
const featureCatalog = { features: [
  { name: "graph_ripple_risk", category: "Graph features", description: "Ripple exposure", available: true, frequency: .9, provenance: ["graph snapshot g-live"], readiness: "ready" },
  { name: "market_return", category: "Market features", description: "Return panel", available: false, readiness: "unavailable", reason: "No historical panel" },
] };
const candidates = { candidates: [
  { candidate_id: "c-1", name: "Ripple", expression: "Rank(graph_ripple_risk)", rationale: "Network effect.", feature_names: ["graph_ripple_risk"], status: "proposed" },
  { candidate_id: "c-2", name: "Inverse ripple", expression: "−Rank(graph_ripple_risk)", rationale: "Direction comparator.", feature_names: ["graph_ripple_risk"], status: "proposed" },
] };
const versions = [{ strategy_id: "s-1", version: 1, name: "Ripple risk strategy", expression: "Rank(graph_ripple_risk)", created_at: "2026-10-02T12:00:00Z", status: "saved" }];
function json(value: unknown, status = 200) { return Promise.resolve(new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } })); }
function renderStudio(hashPinnedExtensionsEnabled = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter><AlphaStudio workspace={workspace} workspaces={[workspace]} offline={false} hashPinnedExtensionsEnabled={hashPinnedExtensionsEnabled} /></MemoryRouter></QueryClientProvider>);
}
function liveApi() {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.endsWith("/graph/snapshots")) return json([{ snapshot_id: "g-live", as_of_time: "2026-09-30T00:00:00Z" }]);
    if (path.endsWith("/features")) return json(featureCatalog);
    if (path.endsWith("/strategies") && init?.method === "POST") return json({ strategy_id: "s-1", version: 1, name: "Ripple risk strategy", expression: "Rank(graph_ripple_risk)", created_at: "2026-10-02T12:00:00Z", status: "saved" }, 201);
    if (path.endsWith("/strategies")) return json([]);
    if (path.endsWith("/alpha-candidates")) return json(candidates);
    if (path.endsWith("/validate")) return json({ valid: true, message: "Expression and portfolio contract passed." });
    if (path.endsWith("/versions")) return json({ versions });
    return json({ detail: "not found" }, 404);
  }));
}
afterEach(() => vi.unstubAllGlobals());

test("feature search and selection keeps unavailable features disabled", async () => {
  liveApi(); const user = userEvent.setup(); renderStudio();
  expect(await screen.findByText("Ripple exposure")).toBeInTheDocument();
  const unavailable = screen.getByRole("checkbox", { name: /market_return/i });
  expect(unavailable).toBeDisabled();
  await user.type(screen.getByRole("textbox", { name: "Search features" }), "market");
  expect(screen.getByText("market_return")).toBeInTheDocument();
  expect(screen.queryByText("graph_ripple_risk")).not.toBeInTheDocument();
});

test("refreshes workspace features, polls the job, and reloads the catalog after success", async () => {
  let finishRefresh: ((response: Response) => void) | undefined;
  let refreshed = false;
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.endsWith("/graph/snapshots")) return json([{ snapshot_id: "g-live", as_of_time: "2026-09-30T00:00:00Z" }]);
    if (path.endsWith("/features")) return json(refreshed ? { features: [...featureCatalog.features, { name: "graph_new", category: "Graph features", description: "New graph feature", available: true, readiness: "ready" }] } : featureCatalog);
    if (path.endsWith("/feature-refresh") && init?.method === "POST") return new Promise<Response>((resolve) => { finishRefresh = resolve; });
    if (path.endsWith("/api/jobs/job-7")) return json({ id: "job-7", kind: "feature-refresh", status: "succeeded", progress: 1, message: "Feature manifest saved." });
    if (path.endsWith("/strategies")) return json([]);
    if (path.endsWith("/alpha-candidates")) return json(candidates);
    return json({ detail: "not found" }, 404);
  }));
  const user = userEvent.setup(); renderStudio();
  const refresh = await screen.findByRole("button", { name: "Refresh features" });
  await user.click(refresh);
  expect(screen.getByText("Submitting feature refresh…")).toBeInTheDocument();
  expect(refresh).toBeDisabled();
  await waitFor(() => expect(finishRefresh).toBeTypeOf("function"));
  refreshed = true;
  finishRefresh?.(new Response(JSON.stringify({ id: "job-7", kind: "feature-refresh", status: "queued", progress: 0, message: "Refresh queued." }), { status: 202, headers: { "Content-Type": "application/json" } }));
  expect(await screen.findByText("Feature refresh succeeded")).toBeInTheDocument();
  expect(screen.getByText("2 ready · 1 unavailable")).toBeInTheDocument();
  expect(screen.getByText("Job job-7")).toBeInTheDocument();
  expect(await screen.findByText("graph_new")).toBeInTheDocument();
  const post = vi.mocked(fetch).mock.calls.find(([path, init]) => String(path).endsWith("/api/workspaces/w-live/feature-refresh") && init?.method === "POST");
  expect(post).toBeDefined();
  expect(JSON.parse(String(post?.[1]?.body)).idempotency_key).toEqual(expect.any(String));
  expect(vi.mocked(fetch).mock.calls.some(([path]) => String(path).endsWith("/api/jobs/job-7"))).toBe(true);
});

test("normalizes feature refresh jobs without losing the id or status", () => {
  expect(normalizeFeatureRefreshReceipt({ job_id: "job-4", status: "running", progress: 0.4, message: "Building" })).toEqual({ id: "job-4", status: "running", progress: 0.4, message: "Building" });
  expect(normalizeFeatureRefreshReceipt(null)).toEqual({ id: "", status: "queued", progress: 0, message: null });
});

test("polls through immediate job status updates to a terminal state", async () => {
  const updates: string[] = [];
  const statuses: Array<"running" | "succeeded"> = ["running", "succeeded"];
  const result = await pollFeatureRefreshJob("job-5", (job) => updates.push(job.status), {
    getJob: async () => ({ id: "job-5", status: statuses.shift(), progress: 1 }),
    wait: async () => undefined,
  });
  expect(updates).toEqual(["running", "succeeded"]);
  expect(result).toMatchObject({ id: "job-5", status: "succeeded" });
});

test("shows a feature refresh error returned by the API", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.endsWith("/graph/snapshots")) return json([{ snapshot_id: "g-live", as_of_time: "2026-09-30T00:00:00Z" }]);
    if (path.endsWith("/features")) return json(featureCatalog);
    if (path.endsWith("/feature-refresh") && init?.method === "POST") return json({ detail: "Feature refresh is temporarily unavailable." }, 503);
    if (path.endsWith("/strategies")) return json([]);
    if (path.endsWith("/alpha-candidates")) return json(candidates);
    return json({ detail: "not found" }, 404);
  }));
  const user = userEvent.setup(); renderStudio();
  await user.click(await screen.findByRole("button", { name: "Refresh features" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Feature refresh is temporarily unavailable.");
});

test("surfaces a failed refresh job without reloading the feature catalog", async () => {
  let featureReads = 0;
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.endsWith("/graph/snapshots")) return json([{ snapshot_id: "g-live", as_of_time: "2026-09-30T00:00:00Z" }]);
    if (path.endsWith("/features")) { featureReads += 1; return json(featureCatalog); }
    if (path.endsWith("/feature-refresh") && init?.method === "POST") return json({ id: "job-fail", status: "queued", progress: 0 }, 202);
    if (path.endsWith("/api/jobs/job-fail")) return json({ id: "job-fail", status: "failed", progress: 0.6, message: "Graph snapshot could not be read." });
    if (path.endsWith("/strategies")) return json([]);
    if (path.endsWith("/alpha-candidates")) return json(candidates);
    return json({ detail: "not found" }, 404);
  }));
  const user = userEvent.setup(); renderStudio();
  await user.click(await screen.findByRole("button", { name: "Refresh features" }));
  expect(await screen.findByText("Feature refresh failed")).toBeInTheDocument();
  expect(await screen.findByRole("alert")).toHaveTextContent("Graph snapshot could not be read.");
  expect(featureReads).toBe(1);
});

test("compares candidates, edits DSL, validates, saves and reads version history", async () => {
  liveApi(); const user = userEvent.setup(); renderStudio();
  await user.click(await screen.findByRole("button", { name: /generate alternatives/i }));
  expect(await screen.findByRole("button", { name: /inverse ripple/i })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /inverse ripple/i }));
  expect(screen.getByRole("textbox", { name: "Strategy expression" })).toHaveValue("−Rank(graph_ripple_risk)");
  await user.clear(screen.getByRole("textbox", { name: "Strategy expression" }));
  await user.type(screen.getByRole("textbox", { name: "Strategy expression" }), "Rank(graph_ripple_risk)");
  await user.click(screen.getByRole("button", { name: "Validate contract" }));
  expect(await screen.findByText("Contract validation passed")).toBeInTheDocument();
  expect(screen.getByText(/not a backtest/i)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Save version" }));
  expect(await screen.findByRole("heading", { name: "Saved versions" })).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: /version 1/i })).toBeInTheDocument();
  const calls = vi.mocked(fetch).mock.calls;
  expect(calls.some(([path]) => String(path).endsWith("/alpha-candidates"))).toBe(true);
  expect(calls.some(([path, init]) => String(path).endsWith("/validate") && init?.method === "POST")).toBe(true);
  expect(calls.some(([path, init]) => String(path).endsWith("/strategies") && init?.method === "POST")).toBe(true);
  expect(calls.some(([path]) => String(path).endsWith("/versions"))).toBe(true);
});

test("is keyboard accessible and fits a 1024px viewport", async () => {
  liveApi(); Object.defineProperty(window, "innerWidth", { configurable: true, value: 1024 });
  const { container } = renderStudio();
  expect(await screen.findByRole("heading", { name: "Shape a testable hypothesis" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Generate alternatives" })).toBeVisible();
  expect((await axe(container)).violations).toEqual([]);
});

test("keeps advanced Python visibly and semantically disabled without the capability", async () => {
  liveApi(); const user = userEvent.setup(); renderStudio();
  await user.click(await screen.findByRole("button", { name: "Generate alternatives" }));
  expect(await screen.findByText("Advanced Python is disabled")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Advanced Python" })).toBeDisabled();
  expect(screen.getByRole("textbox", { name: "Strategy expression" })).toHaveValue("Rank(graph_ripple_risk)");
});

test("loads the Python editor on demand when hash-pinned extensions are enabled", async () => {
  liveApi(); const user = userEvent.setup(); renderStudio(true);
  await user.click(await screen.findByRole("button", { name: "Generate alternatives" }));
  const toggle = await screen.findByRole("button", { name: "Advanced Python" });
  expect(toggle).toBeEnabled();
  await user.click(toggle);
  expect(await screen.findByRole("textbox", { name: "Python extension source" })).toHaveValue("def transform(features):\n    return features\n");
  expect(screen.getByRole("textbox", { name: "Strategy expression" })).toBeInTheDocument();
});

test("edits the constrained expression from the keyboard", async () => {
  liveApi(); const user = userEvent.setup(); renderStudio();
  await user.click(await screen.findByRole("button", { name: "Generate alternatives" }));
  const expression = await screen.findByRole("textbox", { name: "Strategy expression" });
  expression.focus();
  await user.keyboard("{Control>}a{/Control}Rank(graph_ripple_risk)");
  expect(expression).toHaveValue("Rank(graph_ripple_risk)");
});

test("keeps candidates in a truthful demo state when context is missing", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => String(input).endsWith("/features") ? json(featureCatalog) : json({ detail: "not found" }, 404)));
  const looseWorkspace = { ...workspace, universe_id: null, graph_version_id: null };
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><AlphaStudio workspace={looseWorkspace} workspaces={[looseWorkspace]} offline /></MemoryRouter></QueryClientProvider>);
  expect(await screen.findByText(/locked universe and graph snapshot/i)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /generate alternatives/i })).toBeDisabled();
});
