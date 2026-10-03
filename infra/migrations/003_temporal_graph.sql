-- Full immutable graph snapshots; v1 graph_registry files remain untouched.
CREATE TABLE IF NOT EXISTS temporal_graph_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    universe_id TEXT NOT NULL,
    parent_snapshot_id TEXT,
    published_at TIMESTAMPTZ NOT NULL,
    as_of_time TIMESTAMPTZ NOT NULL,
    knowledge_time TIMESTAMPTZ NOT NULL,
    content_sha256 TEXT NOT NULL CHECK (content_sha256 ~ '^[a-fA-F0-9]{64}$'),
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT temporal_graph_snapshot_payload_identity CHECK (
        payload->>'snapshot_id' = snapshot_id
        AND payload->>'workspace_id' = workspace_id
        AND payload->>'universe_id' = universe_id
    )
);

CREATE INDEX IF NOT EXISTS temporal_graph_workspace_published_idx
    ON temporal_graph_snapshots (workspace_id, published_at DESC, snapshot_id DESC);

CREATE OR REPLACE FUNCTION reject_temporal_graph_snapshot_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'temporal graph snapshots are append-only';
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'temporal_graph_snapshots_immutable'
    ) THEN
        CREATE TRIGGER temporal_graph_snapshots_immutable
            BEFORE UPDATE OR DELETE ON temporal_graph_snapshots
            FOR EACH ROW EXECUTE FUNCTION reject_temporal_graph_snapshot_mutation();
    END IF;
END;
$$;
