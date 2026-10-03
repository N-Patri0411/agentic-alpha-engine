import { useEffect, useMemo, useRef, useState } from "react";
import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";
import { Activity, ArrowRight, Clock3, GitCompareArrows, Network, RefreshCw, X } from "lucide-react";
import { NavLink } from "react-router-dom";
import { api, type GraphNode, type GraphRelationship, type GraphRelationshipState, type GraphSnapshot, type GraphSnapshotSummary, type Workspace } from "./api";
import { demoEntities, demoWorkspace } from "./demo";
import "./GraphPage.css";

type Props = { workspaces: Workspace[]; offline: boolean };
type Layer = "economic" | "statistical";
type Direction = "all" | string;

const demoSnapshot = makeDemoSnapshot();
const demoSummary: GraphSnapshotSummary = {
  snapshot_id: demoSnapshot.snapshot_id,
  workspace_id: demoSnapshot.workspace_id,
  as_of_time: demoSnapshot.as_of_time,
  created_at: demoSnapshot.created_at,
  tradeable_connected: 9,
  total_tradeable: 10,
  eligible_relationships: 7,
  total_relationships: 10,
  freshness: 0.91,
};

export function GraphPage({ workspaces, offline }: Props) {
  const queryClient = useQueryClient();
  const [workspaceId, setWorkspaceId] = useState("");
  const [snapshotId, setSnapshotId] = useState("");
  const [compareTo, setCompareTo] = useState("");
  const [layer, setLayer] = useState<Layer>("economic");
  const [selectedTypes, setSelectedTypes] = useState<Set<string> | null>(null);
  const [selectedLifecycles, setSelectedLifecycles] = useState<Set<string> | null>(null);
  const [direction, setDirection] = useState<Direction>("all");
  const [selectedRelationshipId, setSelectedRelationshipId] = useState("");
  const cyRef = useRef<Core | null>(null);
  const canvasRef = useRef<HTMLDivElement | null>(null);

  const sortedWorkspaces = useMemo(
    () => [...workspaces].sort((a, b) => b.created_at.localeCompare(a.created_at)),
    [workspaces],
  );
  useEffect(() => {
    if (!offline && sortedWorkspaces.length && !sortedWorkspaces.some((item) => item.workspace_id === workspaceId)) {
      setWorkspaceId(sortedWorkspaces[0].workspace_id);
      setSnapshotId("");
    }
  }, [offline, sortedWorkspaces, workspaceId]);
  const selectedWorkspace = offline
    ? demoWorkspace
    : sortedWorkspaces.find((item) => item.workspace_id === workspaceId);
  const snapshotsQuery = useQuery({
    queryKey: ["graph-snapshots", selectedWorkspace?.workspace_id],
    queryFn: () => api.graphSnapshots(selectedWorkspace!.workspace_id),
    enabled: Boolean(selectedWorkspace && !offline),
    retry: false,
  });
  const snapshots = offline ? [demoSummary] : snapshotsQuery.data ?? [];
  useEffect(() => {
    if (snapshots.length && !snapshots.some((snapshot) => snapshot.snapshot_id === snapshotId)) {
      setSnapshotId(snapshots[snapshots.length - 1].snapshot_id);
    }
  }, [snapshotId, snapshots]);
  const selectedSummary = snapshots.find((item) => item.snapshot_id === snapshotId) ?? snapshots[snapshots.length - 1];
  const currentQuery = useQuery({
    queryKey: ["graph-snapshot", selectedSummary?.snapshot_id],
    queryFn: () => api.graphSnapshot(selectedSummary!.snapshot_id),
    enabled: Boolean(selectedSummary && !offline),
    retry: false,
  });
  const snapshot = offline ? demoSnapshot : currentQuery.data;
  const refreshMutation = useMutation({
    mutationFn: () => api.refreshGraph(selectedWorkspace!.workspace_id),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["graph-snapshots", selectedWorkspace?.workspace_id] }),
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
      ]);
    },
  });
  const diffQuery = useQuery({
    queryKey: ["graph-snapshot-diff", snapshotId, compareTo],
    queryFn: () => api.graphSnapshotDiff(snapshotId, compareTo),
    enabled: Boolean(snapshotId && compareTo && snapshotId !== compareTo && !offline),
    retry: false,
  });

  const statesById = useMemo(() => new Map((snapshot?.states ?? []).map((item) => [item.relationship_id, item])), [snapshot]);
  const availableTypes = useMemo(() => [...new Set((snapshot?.relationships ?? []).map((item) => item.relationship_type))].sort(), [snapshot]);
  const availableLifecycles = useMemo(() => [...new Set((snapshot?.states ?? []).map((item) => item.lifecycle_status))].sort(), [snapshot]);
  const availableDirections = useMemo(() => [...new Set((snapshot?.relationships ?? []).map((item) => item.direction))].sort(), [snapshot]);
  const visibleRelationships = useMemo(() => (snapshot?.relationships ?? []).filter((relationship) => {
    const state = statesById.get(relationship.relationship_id);
    return (selectedTypes === null || selectedTypes.has(relationship.relationship_type))
      && (selectedLifecycles === null || selectedLifecycles.has(state?.lifecycle_status ?? "unknown"))
      && (direction === "all" || relationship.direction === direction);
  }), [direction, selectedLifecycles, selectedTypes, snapshot, statesById]);
  const selectedRelationship = snapshot?.relationships.find((item) => item.relationship_id === selectedRelationshipId);
  const selectedState = selectedRelationship ? statesById.get(selectedRelationship.relationship_id) : undefined;
  const nodeById = useMemo(() => new Map((snapshot?.nodes ?? []).map((item) => [item.node_id, item])), [snapshot]);
  const snapshotIndex = Math.max(0, snapshots.findIndex((item) => item.snapshot_id === selectedSummary?.snapshot_id));
  const compareOptions = snapshots.filter((item) => item.snapshot_id !== selectedSummary?.snapshot_id);

  useEffect(() => {
    if (!canvasRef.current || !snapshot) return;
    const ids = new Set(snapshot.nodes.map((node) => node.node_id));
    const edges = visibleRelationships.filter((item) => ids.has(item.source_node_id) && ids.has(item.target_node_id));
    const elements: ElementDefinition[] = [
      ...snapshot.nodes.map((node) => ({
        data: { id: node.node_id, label: node.label, tradeable: node.tradeable, nodeKind: node.node_kind },
      })),
      ...edges.map((relationship) => {
        const state = statesById.get(relationship.relationship_id);
        return {
          data: {
            id: relationship.relationship_id,
            source: relationship.source_node_id,
            target: relationship.target_node_id,
            label: shortLabel(relationship.relationship_type),
            exposure: state?.economic_exposure ?? 0,
            propagation: state?.propagation_coefficient ?? 0,
          },
        };
      }),
    ];
    const cy = cytoscape({
      container: canvasRef.current,
      elements,
      layout: { name: "cose", animate: false, fit: true, padding: 36, nodeRepulsion: () => 6500, idealEdgeLength: () => 130 },
      style: [
        { selector: "node", style: { label: "data(label)", color: "#eef0ff", "font-size": "11px", "text-wrap": "wrap", "text-max-width": "90px", "text-valign": "center", "text-halign": "center", width: 62, height: 62, "background-color": "#38334d", "border-width": 2, "border-color": "#8b5cf6", "text-outline-width": 2, "text-outline-color": "#1b1924" } },
        { selector: "node[tradeable = true]", style: { shape: "ellipse", "background-color": "#6e4bc3", "border-color": "#a78bfa", width: 68, height: 68 } },
        { selector: "node[tradeable = false]", style: { shape: "diamond", "background-color": "#0f766e", "border-color": "#5eead4", width: 58, height: 58 } },
        { selector: "edge", style: { label: "data(label)", "font-size": "8px", color: "#aaa8b8", "curve-style": "bezier", "target-arrow-shape": "triangle", "target-arrow-color": "#77718a", "line-color": "#77718a", opacity: 0.76, width: layer === "economic" ? "mapData(exposure, 0, 1, 1, 7)" : "mapData(propagation, 0, 1, 1, 7)" } },
        { selector: "edge:selected", style: { "line-color": "#fbbf24", "target-arrow-color": "#fbbf24", opacity: 1, width: 5 } },
      ],
    });
    cy.on("tap", "edge", (event) => setSelectedRelationshipId(String(event.target.id())));
    cyRef.current = cy;
    return () => { cy.destroy(); cyRef.current = null; };
  }, [layer, snapshot, statesById, visibleRelationships]);

  useEffect(() => {
    if (!compareOptions.length) setCompareTo("");
    else if (!compareOptions.some((item) => item.snapshot_id === compareTo)) setCompareTo(compareOptions[compareOptions.length - 1]?.snapshot_id ?? "");
  }, [compareOptions, compareTo]);

  if (!offline && sortedWorkspaces.length === 0) {
    return <div className="graph-page">
      <PageHeading demo={false} />
      <section className="graph-empty card" aria-labelledby="graph-no-workspace">
        <Network aria-hidden="true" size={34} />
        <h2 id="graph-no-workspace">Start with a domain and locked universe</h2>
        <p>The graph is built from a workspace’s selected instruments. Create a domain first, then return here to inspect its evidence graph.</p>
        <NavLink className="button-primary" to="/new-domain">Create a domain <ArrowRight /></NavLink>
      </section>
    </div>;
  }

  const loadingSnapshots = !offline && snapshotsQuery.isLoading;
  const loadingSnapshot = !offline && Boolean(selectedSummary) && currentQuery.isLoading;
  const failure = snapshotsQuery.error ?? currentQuery.error ?? refreshMutation.error;

  return <div className="graph-page">
    <PageHeading demo={offline} />
    <div className="graph-toolbar card">
      <label className="graph-select-label" htmlFor="graph-workspace">Workspace
        <select id="graph-workspace" className="field" value={selectedWorkspace?.workspace_id ?? ""} disabled={offline || sortedWorkspaces.length < 2} onChange={(event) => { setWorkspaceId(event.target.value); setSnapshotId(""); }}>
          {(offline ? [demoWorkspace] : sortedWorkspaces).map((workspace) => <option key={workspace.workspace_id} value={workspace.workspace_id}>{workspace.name}</option>)}
        </select>
      </label>
      <div className="graph-toolbar-spacer" />
      <p className="graph-context">{selectedWorkspace?.domain} · {selectedWorkspace?.universe_id ? "Locked universe" : "No linked universe"}</p>
      <button className="button-secondary" onClick={() => refreshMutation.mutate()} disabled={offline || !selectedWorkspace?.universe_id || refreshMutation.isPending}>
        <RefreshCw className={refreshMutation.isPending ? "animate-spin" : ""} />{refreshMutation.isPending ? "Queueing…" : "Refresh graph"}
      </button>
    </div>
    {offline && <div className="demo-notice mt-4" role="status"><Network aria-hidden="true" /><div><strong>DEMO graph</strong><p>This sample graph is local fixture data; it was not loaded from a graph snapshot API.</p></div></div>}
    {failure && <div className="graph-error" role="alert"><strong>{refreshMutation.error ? "Refresh could not be queued" : "Graph data could not be loaded"}</strong><span>{failure instanceof Error ? failure.message : "Try loading the graph again."}</span><button className="button-secondary" onClick={() => { void snapshotsQuery.refetch(); if (selectedSummary) void currentQuery.refetch(); }}>Try again</button></div>}
    {loadingSnapshots && <div className="graph-state card" role="status"><Activity className="animate-pulse" /> Loading graph snapshots…</div>}
    {!loadingSnapshots && !failure && snapshots.length === 0 && <div className="graph-empty card" role="status"><Clock3 aria-hidden="true" /><h2>No graph snapshots yet</h2><p>Queue a refresh to build the first evidence snapshot for this workspace.</p><button className="button-primary" onClick={() => refreshMutation.mutate()} disabled={!selectedWorkspace?.universe_id || refreshMutation.isPending}><RefreshCw /> Build first snapshot</button></div>}
    {!loadingSnapshots && !failure && selectedSummary && snapshot && <>
      <section className="graph-snapshot-controls card" aria-label="Snapshot history and graph view">
        <div className="snapshot-heading"><div><span className="eyebrow">Snapshot history</span><strong>{new Date(selectedSummary.as_of_time || selectedSummary.created_at).toLocaleString()}</strong></div><span className="snapshot-count">{snapshotIndex + 1} of {snapshots.length}</span></div>
        <label className="sr-only" htmlFor="snapshot-slider">Select graph snapshot</label>
        <input id="snapshot-slider" className="snapshot-slider" type="range" min={0} max={Math.max(0, snapshots.length - 1)} value={snapshotIndex} aria-valuetext={new Date(selectedSummary.as_of_time || selectedSummary.created_at).toLocaleString()} onChange={(event) => setSnapshotId(snapshots[Number(event.target.value)]?.snapshot_id ?? "")} />
        <div className="snapshot-controls-row">
          <div className="layer-switch" role="group" aria-label="Graph relationship layer">
            <button type="button" aria-pressed={layer === "economic"} onClick={() => setLayer("economic")}>Economic layer</button>
            <button type="button" aria-pressed={layer === "statistical"} onClick={() => setLayer("statistical")}>Statistical layer</button>
          </div>
          <label className="compare-label" htmlFor="compare-snapshot"><GitCompareArrows size={16} /> Compare with
            <select id="compare-snapshot" className="field" value={compareTo} disabled={!compareOptions.length} onChange={(event) => setCompareTo(event.target.value)}>
              {!compareOptions.length && <option value="">No other snapshots</option>}
              {compareOptions.map((item) => <option key={item.snapshot_id} value={item.snapshot_id}>{new Date(item.as_of_time || item.created_at).toLocaleString()}</option>)}
            </select>
          </label>
        </div>
      </section>
      {loadingSnapshot && <div className="graph-state card" role="status"><Activity className="animate-pulse" /> Loading selected snapshot…</div>}
      {!loadingSnapshot && <>
        <section className="graph-metrics" aria-label="Graph coverage and freshness">
          <Metric label="Tradeable connected" value={`${snapshot.coverage.tradeable_connected} / ${snapshot.coverage.total_tradeable}`} detail="instruments in the locked universe" />
          <Metric label="Strategy-eligible" value={`${snapshot.coverage.eligible_relationships} / ${snapshot.coverage.total_relationships}`} detail="relationships meet current gates" />
          <Metric label="Graph freshness" value={formatPercent(snapshot.coverage.freshness)} detail="latest supported evidence" />
          <Metric label="Snapshot" value={new Date(snapshot.created_at || snapshot.as_of_time).toLocaleDateString()} detail={snapshot.snapshot_id} />
        </section>
        <section className="graph-filters card" aria-label="Relationship filters">
          <fieldset><legend>Relationship type</legend><div className="filter-chips">{availableTypes.map((type) => <label key={type} className="filter-chip"><input type="checkbox" checked={selectedTypes === null || selectedTypes.has(type)} onChange={() => setSelectedTypes((current) => toggleFilter(current, type, availableTypes))} />{pretty(type)}</label>)}</div></fieldset>
          <fieldset><legend>Lifecycle</legend><div className="filter-chips">{availableLifecycles.map((status) => <label key={status} className="filter-chip"><input type="checkbox" checked={selectedLifecycles === null || selectedLifecycles.has(status)} onChange={() => setSelectedLifecycles((current) => toggleFilter(current, status, availableLifecycles))} />{pretty(status)}</label>)}</div></fieldset>
          <label className="direction-filter" htmlFor="direction-filter">Direction<select className="field" id="direction-filter" value={direction} onChange={(event) => setDirection(event.target.value)}><option value="all">All directions</option>{availableDirections.map((item) => <option key={item} value={item}>{pretty(item)}</option>)}</select></label>
        </section>
        <div className="graph-layout">
          <section className="card graph-visual-section" aria-labelledby="graph-canvas-heading">
            <div className="graph-section-head"><div><h2 id="graph-canvas-heading">{layer === "economic" ? "Economic exposure" : "Statistical propagation"}</h2><p>Line width reflects {layer === "economic" ? "economic exposure" : "propagation coefficient"}; select an edge to inspect evidence.</p></div><span className="graph-legend"><i className="legend-tradeable" />Tradeable instrument <i className="legend-context" />External context</span></div>
            <div className="graph-canvas" ref={canvasRef} role="img" aria-label={`${layer} relationship graph with ${snapshot.nodes.filter((node) => node.tradeable).length} tradeable instruments and ${snapshot.nodes.filter((node) => !node.tradeable).length} external context nodes`} />
            <div className="graph-node-key" aria-label="Graph nodes">
              {snapshot.nodes.map((node) => <span className={node.tradeable ? "node-key-tradeable" : "node-key-context"} key={node.node_id}><i aria-hidden="true" />{node.label}{node.tradeable ? " · instrument" : " · context"}</span>)}
            </div>
          </section>
          <aside className="card graph-relationships" aria-labelledby="relationship-list-heading">
            <div className="graph-section-head"><div><h2 id="relationship-list-heading">Relationships</h2><p>{visibleRelationships.length} shown · {layer === "economic" ? "economic view" : "statistical view"}</p></div></div>
            <div className="relationship-list">
              {visibleRelationships.map((relationship) => {
                const state = statesById.get(relationship.relationship_id);
                const source = nodeById.get(relationship.source_node_id);
                const target = nodeById.get(relationship.target_node_id);
                return <button className={`relationship-item ${selectedRelationshipId === relationship.relationship_id ? "relationship-item-active" : ""}`} key={relationship.relationship_id} onClick={() => { setSelectedRelationshipId(relationship.relationship_id); cyRef.current?.$id(relationship.relationship_id).select(); }} aria-pressed={selectedRelationshipId === relationship.relationship_id}>
                  <span className="relationship-path">{source?.label ?? "Unknown"} <span aria-hidden="true">→</span> {target?.label ?? "Unknown"}</span>
                  <span className="relationship-subline">{pretty(relationship.relationship_type)} · {pretty(relationship.direction)}</span>
                  <span className="relationship-meta"><span>{formatPercent(state?.confidence ?? 0)} confidence</span><span className={state?.strategy_eligible ? "eligibility-yes" : "eligibility-no"}>{state?.strategy_eligible ? "Strategy eligible" : "Not eligible"}</span></span>
                  <span className="relationship-lifecycle">{pretty(state?.lifecycle_status ?? "unknown")}</span>
                </button>;
              })}
              {!visibleRelationships.length && <p className="empty-filter">No relationships match these filters.</p>}
            </div>
          </aside>
        </div>
        {compareTo && <section className="card graph-diff" aria-labelledby="snapshot-diff-heading">
          <div className="graph-section-head"><div><h2 id="snapshot-diff-heading">Snapshot changes</h2><p>Compared with {new Date(snapshots.find((item) => item.snapshot_id === compareTo)?.as_of_time ?? "").toLocaleString()}</p></div></div>
          {offline ? <p className="empty-filter">Snapshot comparisons are unavailable for demo fixture data.</p>
            : diffQuery.isLoading ? <p className="graph-state-inline" role="status">Loading snapshot diff…</p>
              : diffQuery.error ? <p className="graph-error-inline" role="alert">Could not load snapshot changes. {diffQuery.error instanceof Error ? diffQuery.error.message : "Retry by choosing the comparison again."}</p>
                : diffQuery.data ? <div className="diff-columns">{(["added", "removed", "changed"] as const).map((kind) => <div key={kind} className={`diff-column diff-${kind}`}><strong>{pretty(kind)} <span>{diffQuery.data[kind].length}</span></strong>{diffQuery.data[kind].length ? diffQuery.data[kind].map((item, index) => <p key={String(item.relationship_id ?? item.id ?? index)}>{String(item.label ?? item.relationship_id ?? item.id ?? JSON.stringify(item))}</p>) : <p>None</p>}</div>)}</div>
                  : <p className="empty-filter">Choose another snapshot to compare.</p>}
        </section>}
      </>}
    </>}
    <Dialog.Root open={Boolean(selectedRelationship && selectedState)} onOpenChange={(open) => { if (!open) setSelectedRelationshipId(""); }}>
      <Dialog.Portal><Dialog.Overlay className="fixed inset-0 z-50 bg-black/65 data-[state=open]:animate-fade" />
        <Dialog.Content className="evidence-drawer fixed inset-y-0 right-0 z-50 w-full max-w-md overflow-y-auto border-l border-line bg-panel p-6 shadow-2xl data-[state=open]:animate-slide-in">
          <div className="flex items-start justify-between gap-3"><div><p className="eyebrow">Relationship evidence</p><Dialog.Title className="mt-1 text-xl font-semibold">{selectedRelationship ? `${nodeById.get(selectedRelationship.source_node_id)?.label ?? "Unknown"} → ${nodeById.get(selectedRelationship.target_node_id)?.label ?? "Unknown"}` : "Evidence"}</Dialog.Title><Dialog.Description className="mt-2 text-sm text-muted">{selectedRelationship ? `${pretty(selectedRelationship.relationship_type)} · ${pretty(selectedRelationship.direction)}` : "Select a relationship to inspect its evidence."}</Dialog.Description></div><Dialog.Close className="icon-button" aria-label="Close evidence drawer"><X /></Dialog.Close></div>
          {selectedState && <>
            <div className="drawer-metrics"><Metric label="Confidence" value={formatPercent(selectedState.confidence)} /><Metric label="Economic exposure" value={selectedState.economic_exposure.toFixed(2)} /><Metric label="Propagation coefficient" value={selectedState.propagation_coefficient.toFixed(2)} /><Metric label="Evidence freshness" value={formatPercent(selectedState.freshness)} /></div>
            <div className="drawer-status"><span>{selectedState.strategy_eligible ? "Eligible for strategies" : "Not eligible for strategies"}</span><span>{pretty(selectedState.lifecycle_status)}</span></div>
            <section className="evidence-list"><h3>Evidence IDs ({selectedState.evidence_ids.length})</h3>{selectedState.evidence_ids.length ? <ul>{selectedState.evidence_ids.map((id) => <li key={id}><code>{id}</code></li>)}</ul> : <p>No evidence IDs were attached to this relationship state.</p>}</section>
          </>}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  </div>;
}

function PageHeading({ demo }: { demo: boolean }) {
  return <header className="graph-page-heading"><div><p className="eyebrow">03 · Graph</p><h1>Evidence graph {demo && <span className="demo-badge">DEMO</span>}</h1><p>Explore economic dependencies and statistical propagation, compare snapshots, and inspect relationship evidence.</p></div><NavLink className="button-primary" to="/alpha">Generate Alpha <ArrowRight /></NavLink></header>;
}

function Metric({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return <article className="graph-metric card"><span>{label}</span><strong>{value}</strong>{detail && <small>{detail}</small>}</article>;
}

function toggleFilter(current: Set<string> | null, value: string, all: string[]): Set<string> | null {
  const next = new Set(current ?? all);
  if (next.has(value)) next.delete(value); else next.add(value);
  return next.size === all.length ? null : next;
}

function shortLabel(value: string): string { return value.replaceAll("_", " ").slice(0, 18); }
function pretty(value: string): string { return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()); }
function formatPercent(value: number): string { return `${Math.round((value <= 1 ? value * 100 : value))}%`; }

function makeDemoSnapshot(): GraphSnapshot {
  const tickers = ["NVDA", "AMD", "TSMC", "ASML", "Samsung", "Micron", "Intel", "GlobalFoundries", "Applied Materials", "Lam Research"];
  const nodes: GraphNode[] = [
    ...demoEntities.map((name, index) => ({ node_id: `demo-${index}`, node_kind: "company", label: tickers[index], tradeable: true, instrument_id: `demo-instrument-${index}`, metadata: { display_name: name } })),
    { node_id: "context-ai", node_kind: "demand_context", label: "AI compute demand", tradeable: false, entity_id: "context-ai", metadata: { scope: "external context" } },
    { node_id: "context-controls", node_kind: "policy_context", label: "Export controls", tradeable: false, entity_id: "context-controls", metadata: { scope: "external context" } },
    { node_id: "context-wafer", node_kind: "resource_context", label: "Wafer capacity", tradeable: false, entity_id: "context-wafer", metadata: { scope: "external context" } },
  ];
  const pairs: Array<[string, string, string]> = [
    ["demo-0", "demo-2", "manufacturing_dependency"], ["demo-2", "demo-3", "equipment_dependency"],
    ["demo-2", "demo-8", "equipment_dependency"], ["demo-8", "demo-9", "supplier_relationship"],
    ["demo-1", "demo-7", "foundry_dependency"], ["demo-4", "demo-5", "memory_competition"],
    ["context-ai", "demo-0", "demand_exposure"], ["context-controls", "demo-2", "policy_exposure"],
    ["context-wafer", "demo-2", "capacity_constraint"], ["demo-6", "demo-7", "capacity_competition"],
  ];
  const relationships: GraphRelationship[] = pairs.map(([source, target, type], index) => ({ relationship_id: `demo-rel-${index}`, source_node_id: source, target_node_id: target, relationship_type: type, direction: "forward" }));
  const states: GraphRelationshipState[] = relationships.map((relationship, index) => ({
    relationship_id: relationship.relationship_id,
    confidence: 0.64 + (index % 4) * 0.08,
    economic_exposure: 0.4 + (index % 5) * 0.12,
    propagation_coefficient: 0.12 + (index % 6) * 0.09,
    freshness: 0.75 + (index % 3) * 0.1,
    strategy_eligible: index < 7,
    lifecycle_status: index === 9 ? "candidate" : index === 8 ? "degraded" : "active",
    evidence_ids: [`demo-evidence-${index}-a`, `demo-evidence-${index}-b`],
  }));
  return {
    snapshot_id: "demo-graph-snapshot-v4",
    workspace_id: demoWorkspace.workspace_id,
    universe_id: demoWorkspace.universe_id ?? "demo-universe",
    as_of_time: "2026-09-30T14:30:00Z",
    created_at: "2026-09-30T14:32:00Z",
    nodes,
    relationships,
    states,
    coverage: { tradeable_connected: 9, total_tradeable: 10, eligible_relationships: 7, total_relationships: 10, freshness: 0.91 },
  };
}
