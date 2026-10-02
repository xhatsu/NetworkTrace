-- Caller/target resolution for OTLP spans, written by the worker before aggregation.
-- One row per resolved span. The latest updated_at_ms wins, so re-resolving a window replaces it.
CREATE TABLE IF NOT EXISTS trace_edge_resolutions (
 trace_id String,
 span_id String,
 timestamp_ms Int64,
 override_caller UInt8,
 caller_service String,
 target_service String,
 method LowCardinality(String),
 confidence Float32,
 skip UInt8,
 updated_at_ms UInt64
) ENGINE = ReplacingMergeTree(updated_at_ms)
PARTITION BY toYYYYMMDD(toDateTime(intDiv(timestamp_ms, 1000)))
ORDER BY (trace_id, span_id)
TTL toDateTime(intDiv(timestamp_ms, 1000)) + INTERVAL 2 DAY;
