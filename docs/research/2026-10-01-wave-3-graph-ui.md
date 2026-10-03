# Wave 3 Graph UI contract

The Graph page reads snapshots for the selected workspace, then loads the
selected immutable snapshot and its relationship states. The workspace selector
defaults to the most recently created workspace. A workspace without snapshots
can queue a graph refresh; a user without a workspace is directed to Domain
onboarding.

The page presents two projections of the same snapshot. The economic layer
weights relationships by economic exposure, while the statistical layer uses
the propagation coefficient. Relationship type, lifecycle, and direction
filters apply to both views. The accessible relationship list mirrors the
interactive Cytoscape graph and opens the evidence drawer with confidence,
exposure, propagation, freshness, eligibility, lifecycle, and evidence IDs.

Snapshot history is selected with a date slider. The comparison selector loads
the API diff for added, removed, and changed relationships. Coverage reports
tradeable instrument connectivity and strategy-eligible relationships separately
from snapshot freshness. Tradeable instruments use circular purple nodes;
external context uses teal diamonds. Offline examples are labeled DEMO and are
not presented as API snapshots.

API paths consumed:

- `GET /api/workspaces/{workspace_id}/graph/snapshots`
- `GET /api/graph-snapshots/{snapshot_id}`
- `GET /api/graph-snapshots/{snapshot_id}/diff?compare_to={snapshot_id}`
- `POST /api/workspaces/{workspace_id}/graph-refresh`

The UI normalizes unknown wire values into typed snapshot, relationship, state,
coverage, summary, and diff records. The backend may keep its internal state
collection named `edge_states`; the API adapter exposes the locked `states` wire
field.
