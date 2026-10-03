import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { AlphaStudio } from "../src/AlphaStudio";

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
