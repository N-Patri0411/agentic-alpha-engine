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

export type SelectionMode = "current" | "point_in_time";
export type ProviderCapability = {
  provider_id: string;
  display_name: string;
  capabilities: string[];
  configured: boolean;
  supports_point_in_time?: boolean;
  configuration_status?: "configured" | "unconfigured";
  probe_status?: "not_probed" | "passed" | "failed";
  check_type?: "configuration_check";
  coverage: string;
  limitations: string[];
  check_status?: "not_probed" | "ok" | "failed" | "not_checked";
  check_message?: string | null;
};
export type DomainPlanRequest = {
  description: string;
  regions: string[];
  cadence: Workspace["cadence"];
  base_currency: string;
  selection_mode: SelectionMode;
  selection_time: string | null;
  target_count: number;
};
export type UniverseCompany = {
  instrument_id: string;
  symbol: string;
  name: string;
  exchange: string;
  country: string;
  currency: string;
  figi: string | null;
  sub_industry: string;
  scores: { relevance: number; liquidity: number; coverage: number; total: number };
  reason: string;
  locked: boolean;
};
export type RejectedCandidate = { symbol: string; name: string; reason: string };
export type ProviderCoverage = { provider_id: string; display_name?: string; status: string; detail?: string };
export type DomainPlan = {
  plan_id: string;
  status: string;
  domain_spec: { description: string; expanded_concepts: string[] };
  selection_time: string;
  selection_mode: SelectionMode;
  methodology: string;
  provider_coverage: ProviderCoverage[];
  discovery_yield: Record<string, number>;
  recommended: UniverseCompany[];
  rejected: RejectedCandidate[];
  warnings: string[];
};
type DomainPlanCompanyWire = Partial<UniverseCompany> & {
  company_name?: string;
  relevance_score?: number;
  liquidity_score?: number;
  coverage_score?: number;
  total_score?: number;
};
type DomainPlanWire = Omit<Partial<DomainPlan>, "recommended" | "rejected" | "provider_coverage" | "methodology"> & {
  plan_id: string;
  status: string;
  domain_spec?: { description?: string; expanded_concepts?: string[] };
  selection_time: string;
  selection_mode: SelectionMode;
  selection_method?: string;
  methodology?: string | string[];
  provider_coverage?: ProviderCoverage[] | Record<string, number>;
  recommended?: DomainPlanCompanyWire[];
  rejected?: DomainPlanCompanyWire[];
  replacement_candidates?: DomainPlanCompanyWire[];
  warnings?: string[];
};
export type InstrumentRef = {
  instrument_id: string; symbol: string; exchange: string; country: string | null;
  currency: string; asset_class: "equity" | "etf" | "adr" | "future" | "option" | "cash";
  entity_id: string | null; figi: string | null; provider_symbols: Record<string, string>;
};
export type LockedUniverse = {
  universe_id: string; workspace_id: string; domain: string; instruments: InstrumentRef[];
  selection_time: string; selection_mode: SelectionMode; selection_method: string;
  target_count: number; benchmark: string | null; base_currency: string; version: number;
  created_at: string;
};
export type LockedPlan = { workspace: Workspace; universe: LockedUniverse };

// All Wave 2 wire formats live here; the UI never interacts with ad hoc fetches.
export const normalizeProviderCapabilities = (items: ProviderCapability[]): ProviderCapability[] => items.map((item) => ({
  ...item,
  display_name: item.display_name ?? item.provider_id,
  capabilities: item.capabilities ?? [],
  configured: Boolean(item.configured),
  coverage: item.coverage ?? "Unknown",
  check_status: item.check_status ?? "not_checked",
  limitations: item.limitations ?? [],
}));
function normalizeCompany(company: DomainPlanCompanyWire): UniverseCompany {
  const componentScores = company.scores;
  return {
    instrument_id: company.instrument_id ?? `${company.exchange ?? "unknown"}:${company.symbol ?? "unknown"}`,
    symbol: company.symbol ?? "Unknown",
    name: company.name ?? company.company_name ?? company.symbol ?? "Unknown company",
    exchange: company.exchange ?? "Unknown",
    country: company.country ?? "Unknown",
    currency: company.currency ?? "Unknown",
    figi: company.figi ?? null,
    sub_industry: company.sub_industry ?? "Unclassified",
    scores: {
      relevance: componentScores?.relevance ?? company.relevance_score ?? 0,
      liquidity: componentScores?.liquidity ?? company.liquidity_score ?? 0,
      coverage: componentScores?.coverage ?? company.coverage_score ?? 0,
      total: componentScores?.total ?? company.total_score ?? 0,
    },
    reason: company.reason ?? "No selection reason was provided.",
    locked: Boolean(company.locked),
  };
}
export const normalizeDomainPlan = (plan: DomainPlanWire): DomainPlan & { replacement_candidates: UniverseCompany[] } => {
  const coverage = Array.isArray(plan.provider_coverage)
    ? plan.provider_coverage
    : Object.entries(plan.provider_coverage ?? {}).map(([provider_id, amount]) => ({
      provider_id,
      status: amount > 0 ? "available" : "unavailable",
      detail: `Coverage ${Math.round(amount * 100)}%`,
    }));
  const methods = [plan.selection_method, ...(Array.isArray(plan.methodology) ? plan.methodology : [plan.methodology])].filter((item): item is string => Boolean(item));
  return {
    plan_id: plan.plan_id,
    status: plan.status,
    domain_spec: {
      description: plan.domain_spec?.description ?? "Domain description unavailable",
      expanded_concepts: plan.domain_spec?.expanded_concepts ?? [],
    },
    selection_time: plan.selection_time,
    selection_mode: plan.selection_mode === "point_in_time" ? "point_in_time" : "current",
    methodology: methods.join(" · ") || "Selection methodology unavailable",
    provider_coverage: coverage,
    discovery_yield: plan.discovery_yield ?? {},
    recommended: (plan.recommended ?? []).map(normalizeCompany),
    rejected: (plan.rejected ?? []).map((company) => ({ symbol: company.symbol ?? "Unknown", name: company.name ?? company.company_name ?? company.symbol ?? "Unknown company", reason: company.reason ?? "Rejected candidate." })),
    replacement_candidates: (plan.replacement_candidates ?? []).map(normalizeCompany),
    warnings: plan.warnings ?? [],
  };
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
  providerCapabilities: async () => normalizeProviderCapabilities(await request<ProviderCapability[]>("/api/providers/capabilities")),
  checkProviders: async (providerIds: string[]) => normalizeProviderCapabilities(await request<ProviderCapability[]>("/api/providers/check", { method: "POST", body: JSON.stringify({ provider_ids: providerIds }) })),
  createDomainPlan: async (input: DomainPlanRequest) => normalizeDomainPlan(await request<DomainPlanWire>("/api/domain-plans", { method: "POST", body: JSON.stringify(input) })),
  replacePlanCompany: async (planId: string, removeInstrumentId: string, replacementInstrumentId: string) => normalizeDomainPlan(await request<DomainPlanWire>(`/api/domain-plans/${encodeURIComponent(planId)}/replace`, { method: "POST", body: JSON.stringify({ remove_instrument_id: removeInstrumentId, replacement_instrument_id: replacementInstrumentId }) })),
  lockDomainPlan: (planId: string, workspaceName: string) => request<LockedPlan>(`/api/domain-plans/${encodeURIComponent(planId)}/lock`, { method: "POST", body: JSON.stringify({ workspace_name: workspaceName }) }),
};
