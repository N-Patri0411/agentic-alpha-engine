import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Check, CircleHelp, LockKeyhole, RefreshCw, ShieldCheck } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api, type DomainPlan, type DomainPlanRequest, type ProviderCapability, type UniverseCompany, type Workspace } from "./api";

const steps = ["Describe", "Selection", "Providers", "Generate", "Inspect", "Review", "Workspace"];
const DEMO_AT = "2026-09-30T14:30:00Z";
const demoProviders: ProviderCapability[] = [
  { provider_id: "openfigi", display_name: "OpenFIGI", capabilities: ["instrument mapping"], configured: true, coverage: "Global identifiers", limitations: [] },
  { provider_id: "market-data", display_name: "Market data", capabilities: ["prices", "liquidity"], configured: false, coverage: "US large cap", limitations: ["Credentials are not configured"] },
  { provider_id: "company-filings", display_name: "Company filings", capabilities: ["company facts"], configured: true, coverage: "US filings", limitations: [] },
];
const demoCompanies: UniverseCompany[] = [
  ["US67066G1040", "NVDA", "NVIDIA Corporation", "NASDAQ", "US", "USD", "BBG000BBJQV0", "Semiconductors", 96, "Chip designer with direct exposure to AI compute demand and foundry capacity."],
  ["TW0002330008", "2330", "Taiwan Semiconductor Manufacturing", "TWSE", "TW", "TWD", "BBG000BD8ZK0", "Foundries", 94, "Leading foundry with direct links to advanced node manufacturing."],
  ["NL0010273215", "ASML", "ASML Holding N.V.", "NASDAQ", "NL", "USD", "BBG000F8DYX2", "Semiconductor equipment", 91, "Critical lithography equipment supplier in the advanced chip value chain."],
].map(([instrument_id, symbol, name, exchange, country, currency, figi, sub_industry, score, reason]) => ({
  instrument_id: String(instrument_id), symbol: String(symbol), name: String(name), exchange: String(exchange), country: String(country), currency: String(currency), figi: String(figi), sub_industry: String(sub_industry),
  scores: { relevance: Number(score), liquidity: Number(score) - 4, coverage: Number(score) - 7, total: Number(score) }, reason: String(reason), locked: false,
}));
const demoPlan = (): DomainPlan & { replacement_candidates: UniverseCompany[] } => ({ plan_id: "demo-plan-1", status: "ready", domain_spec: { description: "Semiconductor supply chain", expanded_concepts: ["chip design", "foundries", "equipment", "packaging"] }, selection_time: DEMO_AT, selection_mode: "current", methodology: "DEMO relevance and liquidity ranking with identifier and exchange resolution.", provider_coverage: [{ provider_id: "openfigi", status: "available", detail: "FIGI and exchange mapped" }, { provider_id: "market-data", status: "partial", detail: "Historical liquidity unavailable" }], discovery_yield: {}, recommended: demoCompanies, replacement_candidates: [{ ...demoCompanies[0], instrument_id: "demo-amd", symbol: "AMD", name: "Advanced Micro Devices", figi: "BBG000BB6M98", reason: "DEMO replacement candidate." }], rejected: [{ symbol: "DEMO-X", name: "Example candidate", reason: "Insufficient primary-market coverage." }], warnings: ["Fixture universe: provider data was not queried."] });

type Props = { offline: boolean };
export function DomainOnboarding({ offline }: Props) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [step, setStep] = useState(0);
  const [description, setDescription] = useState("");
  const [regionsText, setRegionsText] = useState("US, TW, NL");
  const [cadence, setCadence] = useState<Workspace["cadence"]>("daily");
  const [currency, setCurrency] = useState("USD");
  const [mode, setMode] = useState<DomainPlanRequest["selection_mode"]>("current");
  const [selectionTime, setSelectionTime] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [providers, setProviders] = useState<ProviderCapability[]>(offline ? demoProviders : []);
  const [providerMessage, setProviderMessage] = useState("");
  const [plan, setPlan] = useState<DomainPlan | null>(offline ? demoPlan() : null);
  const [demo, setDemo] = useState(offline);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [replaceFrom, setReplaceFrom] = useState("");
  const [replaceWith, setReplaceWith] = useState("");
  const [created, setCreated] = useState(false);

  useEffect(() => {
    if (offline) return;
    let alive = true;
    api.providerCapabilities().then((items) => { if (alive) setProviders(items); }).catch((reason: unknown) => {
      if (alive) setProviderMessage(reason instanceof Error ? reason.message : "Provider status is unavailable.");
    });
    return () => { alive = false; };
  }, [offline]);

  const regions = useMemo(() => regionsText.split(",").map((item) => item.trim().toUpperCase()).filter(Boolean), [regionsText]);
  const replacementOptions = useMemo(() => {
    if (!plan) return [];
    const selected = new Set(plan.recommended.map((company) => company.instrument_id));
    return (plan as DomainPlan & { replacement_candidates?: UniverseCompany[] }).replacement_candidates?.filter((item) => !selected.has(item.instrument_id)) ?? [];
  }, [plan]);
  const pointTimeLabel = mode === "current" ? "Selection snapshot" : "As-of selection time";
  const pointInTimeAvailable = demo || providers.some((item) => item.configured && item.supports_point_in_time && item.capabilities.includes("instrument_discovery"));

  async function checkProviders() {
    setBusy(true); setError(""); setProviderMessage("");
    try {
      const result = demo ? demoProviders.map((item) => ({ ...item, check_status: "not_probed" as const, check_message: "DEMO configuration only; no network probe" })) : await api.checkProviders(providers.map((item) => item.provider_id));
      setProviders(result);
      setProviderMessage("Configuration check complete. Credentials are detected locally; provider connectivity and account readiness were not tested.");
    } catch (reason) {
      setProviderMessage(reason instanceof Error ? reason.message : "Provider check failed.");
    } finally { setBusy(false); }
  }

  async function generatePlan() {
    setBusy(true); setError("");
    const input: DomainPlanRequest = { description, regions, cadence, base_currency: currency.trim().toUpperCase(), selection_mode: mode, selection_time: mode === "point_in_time" ? new Date(selectionTime).toISOString() : null, target_count: 10 };
    try {
      const next = demo ? { ...demoPlan(), selection_mode: mode, selection_time: input.selection_time ?? new Date().toISOString() } : await api.createDomainPlan(input);
      setPlan(next); setReplaceFrom(next.recommended[0]?.instrument_id ?? "");
      setReplaceWith((next as DomainPlan & { replacement_candidates?: UniverseCompany[] }).replacement_candidates?.[0]?.instrument_id ?? "");
      setStep(4);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Universe generation failed.");
    } finally { setBusy(false); }
  }

  async function replaceCompany() {
    if (!plan || !replaceFrom || !replaceWith) return;
    setBusy(true); setError("");
    try {
      if (demo) {
        setPlan({ ...plan, recommended: plan.recommended.map((company) => company.instrument_id === replaceFrom ? { ...company, symbol: "AMD", instrument_id: "US0079031078", name: "Advanced Micro Devices", exchange: "NASDAQ", figi: "BBG000BB6M98", reason: "User selected replacement candidate." } : company) });
      } else setPlan(await api.replacePlanCompany(plan.plan_id, replaceFrom, replaceWith));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not replace company."); }
    finally { setBusy(false); }
  }

  async function createWorkspace() {
    setBusy(true); setError("");
    try {
      if (demo) { setCreated(true); return; }
      const result = await api.lockDomainPlan(plan!.plan_id, workspaceName.trim());
      await api.bootstrapWorkspace(result.workspace.workspace_id);
      await queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
      setCreated(true);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not lock the universe and create the workspace."); }
    finally { setBusy(false); }
  }

  function activateDemo() { setDemo(true); setPlan(demoPlan()); setProviders(demoProviders); setError(""); }

  return <div className="mx-auto max-w-5xl">
    <header className="mb-7"><p className="eyebrow">Domain setup</p><h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">Build your investment universe {demo && <span className="demo-badge align-middle">DEMO</span>}</h1><p className="mt-3 max-w-3xl text-sm leading-6 text-muted">Describe the market you want to study, review the companies and their coverage, then lock a reproducible universe.</p></header>
    {demo && <div className="demo-notice mb-6" role="status"><CircleHelp /><div><strong>DEMO fallback</strong><p>The plan service is unavailable. Sample companies and provider status are fixtures; no external data was queried.</p></div></div>}
    <nav className="onboarding-steps mb-7" aria-label="Onboarding progress"><ol>{steps.map((label, index) => <li key={label} aria-current={step === index ? "step" : undefined} className={step === index ? "onboarding-step-active" : step > index ? "onboarding-step-done" : ""}><span>{step > index ? <Check aria-hidden="true" /> : index + 1}</span><span className="onboarding-step-label">{label}</span></li>)}</ol></nav>
    {error && <p role="alert" className="mb-4 rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm">{error}</p>}
    <section className="card p-5 sm:p-7" aria-labelledby="step-title">
      {step === 0 && <><h2 id="step-title" className="text-xl font-semibold">Describe your domain</h2><p className="mt-2 text-sm text-muted">What companies and economic relationships should this strategy cover?</p><label className="field-label mt-6" htmlFor="domain-description">Domain description</label><textarea id="domain-description" className="field mt-2 min-h-32" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="For example, global semiconductor manufacturing and AI compute supply chains" required /><p className="mt-2 text-xs text-muted">Be specific about products, markets, and geographic boundaries.</p><div className="mt-6 flex justify-end"><button className="button-primary" disabled={!description.trim()} onClick={() => setStep(1)}>Continue <ArrowRight /></button></div></>}
      {step === 1 && <><h2 id="step-title" className="text-xl font-semibold">Choose how to select companies</h2><p className="mt-2 text-sm text-muted">Current selection uses the latest available universe. Point-in-time selection freezes the information available at a chosen moment.</p><fieldset className="mt-6 grid gap-3 sm:grid-cols-2"><legend className="field-label mb-2">Selection mode</legend><label className={`selection-card ${mode === "current" ? "selection-card-active" : ""}`}><input type="radio" name="selection-mode" value="current" checked={mode === "current"} onChange={() => setMode("current")} /><span><strong>Current</strong><span>Latest company and market information</span></span></label><label className={`selection-card ${mode === "point_in_time" ? "selection-card-active" : ""}`}><input type="radio" name="selection-mode" value="point_in_time" checked={mode === "point_in_time"} disabled={!pointInTimeAvailable} onChange={() => setMode("point_in_time")} /><span><strong>Point-in-time</strong><span>{pointInTimeAvailable ? "Rebuild using information known then" : "Unavailable: no configured discovery provider guarantees historical results"}</span></span></label></fieldset>{mode === "point_in_time" && <div className="mt-5"><label className="field-label" htmlFor="selection-time">As-of date and time (your local time)</label><input className="field mt-2" id="selection-time" type="datetime-local" value={selectionTime} onChange={(event) => setSelectionTime(event.target.value)} required /><p className="mt-2 text-xs text-muted">Converted to UTC when submitted. Future information is excluded from point-in-time selection.</p></div>}<div className="mt-6 grid gap-4 sm:grid-cols-2"><div><label className="field-label" htmlFor="regions">Regions</label><input className="field mt-2" id="regions" value={regionsText} onChange={(event) => setRegionsText(event.target.value)} /><p className="mt-2 text-xs text-muted">Comma-separated country codes</p></div><div><label className="field-label" htmlFor="cadence">Update cadence</label><select className="field mt-2" id="cadence" value={cadence} onChange={(event) => setCadence(event.target.value as Workspace["cadence"])}><option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option></select></div><div><label className="field-label" htmlFor="currency">Base currency</label><input className="field mt-2" id="currency" maxLength={3} value={currency} onChange={(event) => setCurrency(event.target.value.toUpperCase())} /></div></div><div className="mt-6 flex justify-between"><Back onClick={() => setStep(0)} /><button className="button-primary" disabled={!regions.length || !currency.trim() || (mode === "point_in_time" && !selectionTime)} onClick={() => setStep(2)}>Continue <ArrowRight /></button></div></>}
      {step === 2 && <>
        <h2 id="step-title" className="text-xl font-semibold">Connect data providers</h2>
        <p className="mt-2 text-sm text-muted">Provider credentials stay in your local environment or operating-system vault. This screen never asks for, sends, or displays raw keys.</p>
        <div className="mt-5 flex items-start gap-3 rounded-xl bg-subtle p-4"><ShieldCheck className="shrink-0 text-violet" /><div><strong className="text-sm">Configuration check only</strong><p className="mt-1 text-xs leading-5 text-muted">This checks whether a credential is configured locally. It does not contact the provider, validate the key, or confirm account readiness.</p></div></div>
        {providerMessage && <p className="mt-4 text-sm" role="status">{providerMessage}</p>}
        {providers.length ? <div className="mt-5 grid gap-3">{providers.map((provider) => (
          <article className="provider-row" key={provider.provider_id}>
            <div className="min-w-0"><strong>{provider.display_name}</strong><p>{provider.capabilities.join(" · ") || "Provider capabilities"} · {provider.coverage}</p>{provider.limitations.map((item) => <p className="provider-limitation" key={item}>{item}</p>)}</div>
            <span className={provider.configured ? "provider-status provider-status-ready" : "provider-status provider-status-missing"}>{provider.configured ? "Configured · not probed" : "Not configured · not probed"}</span>
          </article>
        ))}</div> : <p className="mt-5 rounded-lg border border-line p-4 text-sm text-muted">{providerMessage || "Loading provider capabilities…"}</p>}
        <div className="mt-6 flex flex-wrap justify-between gap-3"><Back onClick={() => setStep(1)} /><div className="flex gap-2"><button className="button-secondary" onClick={checkProviders} disabled={busy || !providers.length}><RefreshCw /> Check configuration</button><button className="button-primary" onClick={() => setStep(3)}>Continue <ArrowRight /></button></div></div>
      </>}
      {step === 3 && <><h2 id="step-title" className="text-xl font-semibold">Generate a candidate universe</h2><p className="mt-2 text-sm text-muted">We’ll rank up to 10 companies based on relevance, liquidity, and data coverage. Provider limitations remain visible in the results.</p><div className="mt-5 grid gap-3 sm:grid-cols-3"><Summary label="Regions" value={regions.join(", ")} /><Summary label="Cadence" value={cadence} /><Summary label="Base currency" value={currency.toUpperCase()} /></div><Summary className="mt-3" label={pointTimeLabel} value={mode === "current" ? "At generation time" : `${new Date(selectionTime).toISOString()} UTC`} /><p className="mt-4 text-xs text-muted">Target size: 10 companies. Generation records its timestamp and selection method.</p><div className="mt-6 flex justify-between"><Back onClick={() => setStep(2)} /><button className="button-primary" onClick={generatePlan} disabled={busy}>{busy ? "Generating…" : "Generate universe"} <ArrowRight /></button></div></>}
      {step === 4 && plan && <><h2 id="step-title" className="text-xl font-semibold">Inspect the selection</h2><p className="mt-2 text-sm text-muted">Review selection reasons, scores, identifiers, and provider coverage before making changes.</p><PlanDetails plan={plan} demo={demo} /><div className="mt-6 flex justify-between"><Back onClick={() => setStep(3)} /><button className="button-primary" onClick={() => setStep(5)}>Review companies <ArrowRight /></button></div></>}
      {step === 5 && plan && <><h2 id="step-title" className="text-xl font-semibold">Replace or lock companies</h2><p className="mt-2 text-sm text-muted">Replace a selected company if eligible alternatives were returned, or keep the recommendations and continue.</p><div className="mt-5 grid gap-4 sm:grid-cols-2"><div><label className="field-label" htmlFor="replace-from">Company to replace</label><select id="replace-from" className="field mt-2" value={replaceFrom} onChange={(event) => setReplaceFrom(event.target.value)}>{plan.recommended.map((company) => <option key={company.instrument_id} value={company.instrument_id}>{company.symbol} · {company.name}</option>)}</select></div><div><label className="field-label" htmlFor="replace-with">Replacement company</label><select id="replace-with" className="field mt-2" value={replaceWith} onChange={(event) => setReplaceWith(event.target.value)} disabled={!replacementOptions.length}><option value="">No eligible alternatives returned</option>{replacementOptions.map((company) => <option key={company.instrument_id} value={company.instrument_id}>{company.symbol} · {company.name}</option>)}</select></div></div><button className="button-secondary mt-3" onClick={replaceCompany} disabled={busy || !replaceWith}>Replace company</button><div className="mt-5 rounded-xl border border-line p-4"><div className="flex items-center gap-2"><LockKeyhole className="text-violet" /><strong className="text-sm">Lock the reviewed universe</strong></div><p className="mt-1 text-xs text-muted">Locking records the selected companies and selection method for reproducible downstream work.</p><ul className="mt-3 flex flex-wrap gap-2">{plan.recommended.map((company) => <li className="chip" key={company.instrument_id}>{company.symbol}</li>)}</ul></div><div className="mt-6 flex justify-between"><Back onClick={() => setStep(4)} /><button className="button-primary" onClick={() => setStep(6)}>Continue to workspace <ArrowRight /></button></div></>}
      {step === 6 && <><h2 id="step-title" className="text-xl font-semibold">Create your workspace</h2>{created ? <><p role="status" className="mt-2 text-sm text-green">Universe locked and workspace created{demo ? " · DEMO" : ""}.</p><div className="mt-6 flex justify-end"><button className="button-primary" onClick={() => navigate("/domain")}>Open Domain <ArrowRight /></button></div></> : <><p className="mt-2 text-sm text-muted">Give this strategy workspace a name. Creating it locks the reviewed universe and starts the workspace setup.</p><label htmlFor="workspace-name" className="field-label mt-6">Workspace name</label><input className="field mt-2" id="workspace-name" value={workspaceName} onChange={(event) => setWorkspaceName(event.target.value)} placeholder="Semiconductor supply chain" /><div className="mt-5 rounded-xl bg-subtle p-4"><strong className="text-sm">Ready to create</strong><p className="mt-1 text-xs text-muted">{description} · {plan?.recommended.length ?? 0} selected companies · {mode === "current" ? "Current selection" : `Point-in-time as of ${new Date(selectionTime).toISOString()}`}{demo ? " · DEMO" : ""}</p></div><div className="mt-6 flex justify-between"><Back onClick={() => setStep(5)} /><button className="button-primary" onClick={createWorkspace} disabled={busy || !workspaceName.trim()}>{busy ? "Creating…" : "Lock universe and create workspace"} <Check /></button></div></>}</>}
    </section>
    {!demo && step >= 3 && <div className="mt-4 text-right"><button className="text-xs text-muted underline" onClick={activateDemo}>Use labeled demo data</button></div>}
  </div>;
}

function PlanDetails({ plan, demo }: { plan: DomainPlan; demo: boolean }) {
  return <div className="mt-5 space-y-5"><div className="selection-meta"><Summary label="Selection mode" value={plan.selection_mode === "current" ? "Current" : "Point-in-time"} /><Summary label="Selection timestamp (UTC)" value={`${new Date(plan.selection_time).toISOString()}${demo ? " · DEMO" : ""}`} /><Summary label="Methodology" value={plan.methodology} /></div><div><h3 className="mb-2 text-sm font-semibold">Recommended companies ({plan.recommended.length})</h3><div className="overflow-x-auto rounded-xl border border-line"><table className="company-table"><caption className="sr-only">Recommended universe companies, scores, identifiers, and selection reasons</caption><thead><tr><th>Company</th><th>FIGI · Exchange</th><th>Scores</th><th>Why selected</th></tr></thead><tbody>{plan.recommended.map((company) => <tr key={company.instrument_id}><td><strong>{company.symbol}</strong><span>{company.name}</span><small>{company.country} · {company.currency} · {company.sub_industry}</small></td><td>{company.figi ?? "Unavailable"}<span>{company.exchange}</span></td><td><strong>{company.scores.total}</strong><span>Relevance {company.scores.relevance} · Liquidity {company.scores.liquidity} · Data coverage {company.scores.coverage}</span></td><td>{company.reason}</td></tr>)}</tbody></table></div></div><div className="grid gap-4 md:grid-cols-3"><section className="rounded-xl border border-line p-4"><h3 className="text-sm font-semibold">Historical data coverage</h3>{plan.provider_coverage.map((item) => <p className="mt-2 text-xs text-muted" key={item.provider_id}><strong className="text-ink">{item.display_name ?? item.provider_id}</strong> · {item.status}{item.detail ? ` — ${item.detail}` : ""}</p>)}</section><section className="rounded-xl border border-line p-4"><h3 className="text-sm font-semibold">Discovery yield</h3>{Object.entries(plan.discovery_yield).map(([provider, value]) => <p className="mt-2 text-xs text-muted" key={provider}><strong className="text-ink">{provider}</strong> · {Math.round(value * 100)}% of target</p>)}{!Object.keys(plan.discovery_yield).length && <p className="mt-2 text-xs text-muted">Not reported.</p>}</section><section className="rounded-xl border border-line p-4"><h3 className="text-sm font-semibold">Unavailable or rejected</h3>{plan.rejected.length ? plan.rejected.map((item) => <p className="mt-2 text-xs text-muted" key={`${item.symbol}-${item.reason}`}><strong className="text-ink">{item.symbol} · {item.name}</strong> — {item.reason}</p>) : <p className="mt-2 text-xs text-muted">No rejected candidates.</p>}{plan.warnings.map((item) => <p className="mt-2 text-xs text-amber" key={item}>{item}</p>)}</section></div></div>;
}
function Summary({ label, value, className = "" }: { label: string; value: string; className?: string }) { return <div className={`summary-box ${className}`}><span>{label}</span><strong>{value}</strong></div>; }
function Back({ onClick }: { onClick: () => void }) { return <button className="button-secondary" onClick={onClick}><ArrowLeft /> Back</button>; }
