-- Per-credential five-minute activity rollup. User behavior (principal intelligence,
-- behavioral detectors, user/IP anomaly detection) reads only this table, never raw traces.
-- The worker rewrites a whole window per aggregation slice from the caller-resolved trace
-- source. One row per (bucket, row_key), and row_key hashes every dimension column.
-- Retained 35 days so 28-day time-of-week readiness is reachable (raw traces keep 1 day).
CREATE TABLE IF NOT EXISTS principal_activity_5m (
 bucket_start_ms Int64,
 row_key UInt64,
 environment LowCardinality(String),
 principal_id String,
 principal_name String,
 caller_service String,
 caller_instance String,
 source_ip String,
 ip_resolution LowCardinality(String),
 source_group String,
 target_service String,
 target_instance String,
 target_ip String,
 target_port UInt16,
 operation String,
 operation_key String,
 http_method LowCardinality(String),
 auth_evidence LowCardinality(String),
 request_count UInt64,
 error_count UInt64,
 auth_failure_count UInt64,
 auth_success_count UInt64,
 first_seen_ms Int64,
 last_seen_ms Int64,
 last_failure_ms Int64,
 last_success_ms Int64,
 sample_trace_ids Array(String),
 updated_at_ms UInt64,
 INDEX idx_principal_activity_pid principal_id TYPE bloom_filter GRANULARITY 4,
 INDEX idx_principal_activity_updated updated_at_ms TYPE minmax GRANULARITY 4
) ENGINE = ReplacingMergeTree(updated_at_ms)
PARTITION BY toYYYYMMDD(toDateTime(intDiv(bucket_start_ms, 1000)))
ORDER BY (bucket_start_ms, row_key)
TTL toDateTime(intDiv(bucket_start_ms, 1000)) + INTERVAL 35 DAY;

-- What principal intelligence already counted for each rollup row. A rewritten row is
-- processed again only for the difference, so re-aggregating a window never double counts.
CREATE TABLE IF NOT EXISTS principal_activity_consumed (
 bucket_start_ms Int64,
 row_key UInt64,
 request_count UInt64,
 error_count UInt64,
 auth_failure_count UInt64,
 auth_success_count UInt64,
 updated_at_ms UInt64
) ENGINE = ReplacingMergeTree(updated_at_ms)
PARTITION BY toYYYYMMDD(toDateTime(intDiv(bucket_start_ms, 1000)))
ORDER BY (bucket_start_ms, row_key)
TTL toDateTime(intDiv(bucket_start_ms, 1000)) + INTERVAL 35 DAY;
