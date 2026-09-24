-- Service instance inventory is a worker-maintained read model for the service API.
CREATE TABLE IF NOT EXISTS service_instance_edges_5m (
    bucket_start Int64,
    target_service String,
    service_instance String,
    request_count UInt64 DEFAULT 0,
    error_count UInt64 DEFAULT 0,
    latency_sum Float64 DEFAULT 0.0,
    p95_latency_ms Float64 DEFAULT 0.0,
    first_seen_ms UInt64 DEFAULT 0,
    last_seen_ms UInt64 DEFAULT 0,
    updated_at_ms UInt64
) ENGINE = ReplacingMergeTree(updated_at_ms)
PARTITION BY toYYYYMM(toDateTime(bucket_start))
ORDER BY (bucket_start, target_service, service_instance);
