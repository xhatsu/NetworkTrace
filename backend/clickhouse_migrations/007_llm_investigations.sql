-- Additive, versioned persistence for explicit investigations of existing findings.
CREATE TABLE IF NOT EXISTS llm_investigations (
    id UUID,
    dedup_key FixedString(64),
    retry_index UInt8,
    retry_of Nullable(UUID),
    finding_kind LowCardinality(String),
    finding_id String,
    source_version FixedString(64),
    snapshot_schema_version String,
    prompt_version String,
    result_schema_version String,
    policy_version String,
    provider String,
    configured_model String,
    reported_model Nullable(String),
    state LowCardinality(String),
    state_version UInt64,
    cancel_requested UInt8,
    created_at_ms UInt64,
    updated_at_ms UInt64,
    started_at_ms Nullable(UInt64),
    finished_at_ms Nullable(UInt64),
    deadline_ms UInt64,
    expires_at DateTime64(3, 'UTC'),
    snapshot_json String,
    evidence_json String,
    evidence_digest Nullable(String),
    deterministic_summary_json String,
    result_json Nullable(String),
    failure_code Nullable(String),
    metadata_json String
) ENGINE = ReplacingMergeTree(state_version)
ORDER BY (finding_kind, finding_id, id)
-- ClickHouse 24.x requires a Date/DateTime TTL expression even though the
-- persisted expiry keeps millisecond precision for API filtering.
TTL toDateTime(expires_at) DELETE;
