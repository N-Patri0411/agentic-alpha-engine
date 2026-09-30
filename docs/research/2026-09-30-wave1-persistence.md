# Wave 1 product persistence note

Wave 1 introduces versioned product contracts under `alpha_workbench.product`
and append-only repositories under `alpha_workbench.persistence`.  Product
records are kept in `product_*` PostgreSQL tables so the existing evidence,
graph, and research ledgers remain compatible and untouched.

Each immutable record is addressed by `(logical_id, version)` and stores a
canonical JSON payload plus a SHA-256 digest.  Repeating an identical write is
idempotent; writing different content to an existing version raises an error.
Operational job receipts, queue state, and progress events are owned by the
canonical `alpha_workbench.jobs` package and its `jobs`/`job_events` tables.
The product persistence layer intentionally does not duplicate those models or
tables.

Universe contracts require both an explicit timezone-aware `selection_time`
and `selection_mode` (`current` or `point_in_time`).  The selected instruments
are separate from economic entities, allowing later graph work to include
non-tradeable context nodes without changing strategy universes.
