-- Append-only feature definitions, feature set pins, and computed frame manifests.
CREATE TABLE IF NOT EXISTS feature_artifacts (
    artifact_kind TEXT NOT NULL CHECK (artifact_kind IN ('definition', 'feature_set', 'observation', 'manifest')),
    artifact_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    content_sha256 TEXT NOT NULL CHECK (content_sha256 ~ '^[a-fA-F0-9]{64}$'),
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (artifact_kind, artifact_id, version),
    CONSTRAINT feature_artifact_payload_identity CHECK (
        CASE artifact_kind
            WHEN 'definition' THEN payload->>'feature_id' = artifact_id
            WHEN 'feature_set' THEN payload->>'feature_set_id' = artifact_id
            WHEN 'observation' THEN artifact_id LIKE 'feature-observation-%'
            WHEN 'manifest' THEN payload->>'manifest_id' = artifact_id
            ELSE FALSE
        END
        AND payload->>'version' = version::text
    )
);

CREATE INDEX IF NOT EXISTS feature_artifacts_kind_id_idx
    ON feature_artifacts (artifact_kind, artifact_id, version DESC);

CREATE OR REPLACE FUNCTION reject_feature_artifact_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'feature artifacts are append-only';
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'feature_artifacts_immutable'
    ) THEN
        CREATE TRIGGER feature_artifacts_immutable
            BEFORE UPDATE OR DELETE ON feature_artifacts
            FOR EACH ROW EXECUTE FUNCTION reject_feature_artifact_mutation();
    END IF;
END;
$$;

-- Workspace readiness is explicit and append-only. A global feature definition
-- does not imply the feature is built or usable for any particular workspace.
CREATE TABLE IF NOT EXISTS workspace_feature_bindings (
    workspace_id TEXT NOT NULL,
    feature_id TEXT NOT NULL,
    feature_version INTEGER NOT NULL CHECK (feature_version >= 1),
    version INTEGER NOT NULL CHECK (version >= 1),
    content_sha256 TEXT NOT NULL CHECK (content_sha256 ~ '^[a-fA-F0-9]{64}$'),
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (workspace_id, feature_id, version),
    CHECK (payload->>'workspace_id' = workspace_id),
    CHECK (payload->>'feature_id' = feature_id),
    CHECK (payload->>'feature_version' = feature_version::text),
    CHECK (payload->>'version' = version::text)
);

CREATE INDEX IF NOT EXISTS workspace_feature_bindings_latest_idx
    ON workspace_feature_bindings (workspace_id, feature_id, version DESC);

CREATE OR REPLACE FUNCTION reject_workspace_feature_binding_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'workspace feature bindings are append-only';
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'workspace_feature_bindings_immutable'
    ) THEN
        CREATE TRIGGER workspace_feature_bindings_immutable
            BEFORE UPDATE OR DELETE ON workspace_feature_bindings
            FOR EACH ROW EXECUTE FUNCTION reject_workspace_feature_binding_mutation();
    END IF;
END;
$$;

-- Formula rows deduplicate retries; a per-experiment counter is protected by
-- the transaction-level advisory lock in PostgresTrialLedger.
CREATE TABLE IF NOT EXISTS experiment_trial_counters (
    experiment_id TEXT PRIMARY KEY,
    trial_count INTEGER NOT NULL CHECK (trial_count >= 0)
);

CREATE TABLE IF NOT EXISTS experiment_trials (
    experiment_id TEXT NOT NULL REFERENCES experiment_trial_counters(experiment_id)
        DEFERRABLE INITIALLY DEFERRED,
    canonical_formula TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (experiment_id, canonical_formula)
);
