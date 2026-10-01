import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "../src/App";

const workspace = { workspace_id: "w-1", name: "Energy Transition", domain: "energy", base_currency: "USD", cadence: "daily", regions: ["US"], universe_id: null, graph_version_id: null, status: "ready", provider_ids: [], version: 1, created_at: "2026-09-30T12:00:00Z" };
const job = { id: "j-1", kind: "workspace-bootstrap", status: "running", created_at: "2026-09-30T12:00:00Z", started_at: "2026-09-30T12:00:01Z", finished_at: null, progress: 0.5, message: "Building workspace", cancel_requested: false };

function json(value: unknown, status = 200) { return Promise.resolve(new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } })); }
function renderApp(path = "/") { const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>); }
function mockLiveApi() { vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => { const path = String(input); if (path === "/api/health") return json({ status: "ok" }); if (path === "/api/workspaces" && init?.method === "POST") return json(workspace, 201); if (path === "/api/workspaces") return json([workspace]); if (path === "/api/jobs" && init?.method === "POST") return json(job, 202); if (path === "/api/jobs") return json([job]); return json({ detail: "not found" }, 404); })); }

afterEach(() => { vi.unstubAllGlobals(); });

test("renders the production workflow from Domain through Monitor", async () => {
  mockLiveApi(); renderApp();
  expect(await screen.findByRole("heading", { name: "Agentic Alpha Studio" })).toBeInTheDocument();
  for (const label of ["Domain", "Universe", "Graph", "Alpha", "Backtest", "Paper / Code Export", "Monitor"]) expect(screen.getAllByRole("link", { name: new RegExp(label, "i") }).length).toBeGreaterThan(0);
  expect(screen.queryByText(/human review|awaiting review|gatekeeper/i)).not.toBeInTheDocument();
});

test("shows an explicit demo fallback when the API is offline", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("offline")))); renderApp();
  expect(await screen.findByText("Demo fallback")).toBeInTheDocument();
  expect(screen.getAllByText("DEMO").length).toBeGreaterThan(0);
});

const provider = { provider_id: "openfigi", display_name: "OpenFIGI", capabilities: ["instrument_discovery", "instrument mapping"], supports_point_in_time: true, configured: true, coverage: "Global", limitations: [] };
const company = { instrument_id: "i-1", symbol: "NVDA", company_name: "NVIDIA Corporation", exchange: "NASDAQ", country: "US", currency: "USD", figi: "BBG000BBJQV0", sub_industry: "Semiconductors", relevance_score: 96, liquidity_score: 92, coverage_score: 88, total_score: 94, reason: "High relevance and strong coverage.", locked: false };
const replacement = { ...company, instrument_id: "i-2", symbol: "AMD", figi: "BBG000BB6M98", company_name: "Advanced Micro Devices" };
const plan = { plan_id: "p-1", status: "ready", domain_spec: { description: "semiconductors", expanded_concepts: ["foundries"] }, selection_time: "2026-09-30T14:30:00Z", selection_mode: "current", selection_method: "Provider-ranked selection", methodology: ["Relevance and liquidity ranking"], provider_coverage: { openfigi: 0.85 }, recommended: [company], rejected: [{ ...company, symbol: "BAD", company_name: "Unavailable Co", reason: "No active exchange listing." }], warnings: [], replacement_candidates: [replacement] };
const lockedPlan = { workspace: { ...workspace, name: "Semiconductor supply chain", domain: "chips", universe_id: "u-1" }, universe: { universe_id: "u-1" } };
function mockOnboardingApi({ providerFailure = false } = {}) {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path === "/api/health") return json({ status: "ok" });
    if (path === "/api/workspaces") return json([workspace]);
    if (path === "/api/jobs" && init?.method === "POST") return json(job, 202);
    if (path === "/api/jobs") return json([job]);
    if (path === "/api/providers/capabilities") return json([provider]);
    if (path === "/api/providers/check") return providerFailure ? json({ detail: "Provider timed out" }, 503) : json([{ ...provider, check_type: "configuration_check", configuration_status: "configured", probe_status: "not_probed", check_status: "not_probed" }]);
    if (path === "/api/domain-plans" && init?.method === "POST") {
      const request = JSON.parse(String(init.body)) as { selection_mode: string; selection_time: string | null };
      return json({ ...plan, selection_mode: request.selection_mode, selection_time: request.selection_time ?? "2026-09-30T14:30:00Z" }, 201);
    }
  if (path === "/api/domain-plans/p-1/replace") return json({ ...plan, recommended: [{ ...company, symbol: "AMD", instrument_id: "i-2", company_name: "Advanced Micro Devices" }] });
    if (path === "/api/domain-plans/p-1/lock") return json(lockedPlan);
    return json({ detail: "not found" }, 404);
  }));
}
async function goThroughPlanSetup(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByRole("heading", { name: /build your investment universe/i });
  await user.type(screen.getByLabelText("Domain description"), "Semiconductor supply chain");
  await user.click(screen.getByRole("button", { name: /continue/i }));
  await user.click(screen.getByRole("button", { name: /continue/i }));
  await user.click(screen.getByRole("button", { name: /check configuration/i }));
  await user.click(screen.getByRole("button", { name: /continue/i }));
  await user.click(screen.getByRole("button", { name: /generate universe/i }));
  await screen.findByRole("heading", { name: "Inspect the selection" });
}

test("runs the seven-step wizard, replaces a company, locks the plan, and creates a workspace", async () => {
  mockOnboardingApi(); const user = userEvent.setup(); const app = renderApp("/new-domain");
  await goThroughPlanSetup(user);
  expect(screen.getByText("High relevance and strong coverage.")).toBeInTheDocument();
  expect(app.container.textContent).toContain("No active exchange listing.");
  expect(screen.getByText("BBG000BBJQV0")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /review companies/i }));
  await user.selectOptions(screen.getByLabelText("Replacement company"), "i-2");
  await user.click(screen.getByRole("button", { name: /replace company/i }));
  await screen.findByText("AMD", { selector: "li" });
  await user.click(screen.getByRole("button", { name: /continue to workspace/i }));
  await user.type(screen.getByLabelText("Workspace name"), "Semiconductor supply chain");
  await user.click(screen.getByRole("button", { name: /lock universe and create workspace/i }));
  expect(await screen.findByText(/Universe locked and workspace created/)).toBeInTheDocument();
  const calls = vi.mocked(fetch).mock.calls;
  expect(calls.some(([path, init]) => path === "/api/domain-plans" && init?.method === "POST" && JSON.parse(String(init.body)).target_count === 10)).toBe(true);
  expect(JSON.parse(String(calls.find(([path, init]) => path === "/api/domain-plans" && init?.method === "POST")?.[1]?.body)).selection_time).toBeNull();
  expect(calls.some(([path]) => path === "/api/domain-plans/p-1/replace")).toBe(true);
  expect(calls.some(([path]) => path === "/api/domain-plans/p-1/lock")).toBe(true);
  expect(calls.some(([path, init]) => path === "/api/jobs" && init?.method === "POST")).toBe(true);
});

test("captures a point-in-time selection in UTC and labels it distinctly", async () => {
  mockOnboardingApi(); const user = userEvent.setup(); renderApp("/new-domain");
  await screen.findByRole("heading", { name: /build your investment universe/i });
  await user.type(screen.getByLabelText("Domain description"), "Semiconductors");
  await user.click(screen.getByRole("button", { name: /continue/i }));
  await user.click(screen.getByRole("radio", { name: /point-in-time/i }));
  const localTime = "2024-01-02T15:04";
  await user.type(screen.getByLabelText(/as-of date and time/i), localTime);
  expect(screen.getByText(/Converted to UTC when submitted/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /continue/i }));
  await user.click(screen.getByRole("button", { name: /continue/i }));
  expect(screen.getByText(new RegExp(`${new Date(localTime).toISOString()} UTC`))).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /generate universe/i }));
  await screen.findByRole("heading", { name: "Inspect the selection" });
  expect(screen.getByText("Point-in-time", { selector: "strong" })).toBeInTheDocument();
  const createCall = vi.mocked(fetch).mock.calls.find(([path, init]) => path === "/api/domain-plans" && init?.method === "POST");
  expect(JSON.parse(String(createCall?.[1]?.body)).selection_time).toBe(new Date(localTime).toISOString());
});

test("labels provider checks as configuration-only and never presents a credential entry field", async () => {
  mockOnboardingApi(); const user = userEvent.setup(); renderApp("/new-domain");
  await screen.findByRole("heading", { name: /build your investment universe/i });
  await user.type(screen.getByLabelText("Domain description"), "Semiconductors");
  await user.click(screen.getByRole("button", { name: /continue/i })); await user.click(screen.getByRole("button", { name: /continue/i }));
  expect(await screen.findByText("OpenFIGI")).toBeInTheDocument();
  expect(screen.queryByLabelText(/key|secret|token/i)).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /check configuration/i }));
  expect(await screen.findByRole("status")).toHaveTextContent(/connectivity and account readiness were not tested/i);
});

test("supports keyboard navigation and has no axe violations during onboarding", async () => {
  mockOnboardingApi(); const user = userEvent.setup(); const { container } = renderApp("/new-domain");
  await screen.findByRole("heading", { name: /build your investment universe/i });
  await user.tab(); expect(screen.getByRole("link", { name: "Skip to content" })).toHaveFocus();
  expect((await axe(container)).violations).toEqual([]);
});

test("keeps the wizard usable at a 1024px viewport", async () => {
  mockOnboardingApi(); Object.defineProperty(window, "innerWidth", { configurable: true, value: 1024 });
  renderApp("/new-domain");
  expect(await screen.findByRole("heading", { name: /build your investment universe/i })).toBeInTheDocument();
  expect(screen.getByRole("navigation", { name: "Onboarding progress" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /continue/i })).toBeVisible();
});

test("opens the accessible global jobs dialog", async () => {
  mockLiveApi(); const user = userEvent.setup(); renderApp();
  await user.click(await screen.findByRole("button", { name: /1 active job/i }));
  expect(screen.getByRole("dialog", { name: "Jobs" })).toBeInTheDocument();
  expect(screen.getByText("Building workspace")).toBeInTheDocument();
});

test("has no axe violations on the home shell", async () => {
  mockLiveApi(); const { container } = renderApp(); await waitFor(() => expect(screen.getByText("Connected")).toBeInTheDocument());
  expect((await axe(container)).violations).toEqual([]);
});
