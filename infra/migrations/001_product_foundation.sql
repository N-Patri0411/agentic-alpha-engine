-- Immutable, versioned product records. Operational jobs live in 002_jobs.sql.
CREATE TABLE IF NOT EXISTS product_workspaces (
    workspace_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    content_sha256 TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (workspace_id, version)
);

CREATE TABLE IF NOT EXISTS product_universe_versions (
    universe_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    content_sha256 TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (universe_id, version)
);

CREATE TABLE IF NOT EXISTS product_provider_capabilities (
    provider_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    content_sha256 TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (provider_id, version)
);

CREATE TABLE IF NOT EXISTS product_strategy_versions (
    strategy_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    content_sha256 TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (strategy_id, version)
);

CREATE TABLE IF NOT EXISTS product_strategy_runs (
    run_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    content_sha256 TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, version)
);

CREATE TABLE IF NOT EXISTS product_strategy_packages (
    package_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    content_sha256 TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (package_id, version)
);

CREATE TABLE IF NOT EXISTS product_readiness_reports (
    readiness_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    content_sha256 TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (readiness_id, version)
);

CREATE OR REPLACE FUNCTION reject_product_record_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'versioned product records are immutable';
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'product_workspaces',
        'product_universe_versions',
        'product_provider_capabilities',
        'product_strategy_versions',
        'product_strategy_runs',
        'product_strategy_packages',
        'product_readiness_reports'
    ]
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS reject_mutation ON %I', table_name);
        EXECUTE format(
            'CREATE TRIGGER reject_mutation BEFORE UPDATE OR DELETE ON %I '
            'FOR EACH ROW EXECUTE FUNCTION reject_product_record_mutation()',
            table_name
        );
    END LOOP;
END;
$$;
