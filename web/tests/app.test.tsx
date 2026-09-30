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
  for (const label of ["Domain", "Universe", "Graph", "Alpha", "Backtest", "Paper / LEAN Export", "Monitor"]) expect(screen.getAllByRole("link", { name: new RegExp(label, "i") }).length).toBeGreaterThan(0);
  expect(screen.queryByText(/human review|awaiting review|gatekeeper/i)).not.toBeInTheDocument();
});

test("shows an explicit demo fallback when the API is offline", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("offline")))); renderApp();
  expect(await screen.findByText("Demo fallback")).toBeInTheDocument();
  expect(screen.getAllByText("DEMO").length).toBeGreaterThan(0);
});

test("creates a workspace and submits its bootstrap job", async () => {
  mockLiveApi(); const user = userEvent.setup(); renderApp("/new-domain");
  await screen.findByRole("heading", { name: "Create a strategy domain" });
  await user.type(screen.getByLabelText("Workspace name"), "Energy Transition");
  await user.type(screen.getByLabelText("Domain thesis"), "Energy supply chains");
  await user.type(screen.getByLabelText("Regions"), "US, CA");
  await user.click(screen.getByRole("button", { name: /create and start/i }));
  await screen.findByRole("heading", { name: "Energy Transition" });
  const calls = vi.mocked(fetch).mock.calls;
  expect(calls.some(([path, init]) => path === "/api/workspaces" && init?.method === "POST")).toBe(true);
  expect(calls.some(([path, init]) => path === "/api/jobs" && init?.method === "POST")).toBe(true);
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
