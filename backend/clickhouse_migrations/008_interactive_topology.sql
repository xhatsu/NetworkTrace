-- Interactive service -> API -> principal topology rollups.
-- ClickHouse deployments build these from raw spans in bounded worker slices.
-- Elasticsearch mode reads the equivalent worker metric_buckets projection;
-- raw application spans remain in Elasticsearch and are never an API query source.

ALTER TABLE traces ADD COLUMN IF NOT EXISTS observed_ip Nullable(String);
ALTER TABLE traces ADD COLUMN IF NOT EXISTS effective_client_ip Nullable(String);
ALTER TABLE traces ADD COLUMN IF NOT EXISTS ip_resolution LowCardinality(String) DEFAULT 'unknown';
ALTER TABLE traces ADD COLUMN IF NOT EXISTS client_identity_quality LowCardinality(String) DEFAULT 'low';
ALTER TABLE traces ADD COLUMN IF NOT EXISTS context_quality LowCardinality(String) DEFAULT 'low';
ALTER TABLE traces ADD COLUMN IF NOT EXISTS traffic_class LowCardinality(String) DEFAULT 'identified';
ALTER TABLE traces ADD COLUMN IF NOT EXISTS is_agent_trace UInt8 DEFAULT 0;
ALTER TABLE traces ADD COLUMN IF NOT EXISTS request_bytes Nullable(UInt64);
ALTER TABLE traces ADD COLUMN IF NOT EXISTS response_bytes Nullable(UInt64);

CREATE TABLE IF NOT EXISTS topology_service_edges_5m (
    bucket_start Int64,
    caller_service String,
    target_service String,
    request_count UInt64 DEFAULT 0,
    error_count UInt64 DEFAULT 0,
    http_4xx_count UInt64 DEFAULT 0,
    http_5xx_count UInt64 DEFAULT 0,
    timeout_count UInt64 DEFAULT 0,
    tcp_reset_count UInt64 DEFAULT 0,
    incomplete_count UInt64 DEFAULT 0,
    latency_sum Float64 DEFAULT 0.0,
    p50_latency_ms Float64 DEFAULT 0.0,
    p95_latency_ms Float64 DEFAULT 0.0,
    p99_latency_ms Float64 DEFAULT 0.0,
    request_bytes UInt64 DEFAULT 0,
    response_bytes UInt64 DEFAULT 0,
    unique_principals UInt64 DEFAULT 0,
    unique_source_ips UInt64 DEFAULT 0,
    anonymous_requests UInt64 DEFAULT 0,
    first_seen_ms UInt64 DEFAULT 0,
    last_seen_ms UInt64 DEFAULT 0,
    evidence_type LowCardinality(String) DEFAULT 'OTEL_CLIENT_SERVER',
    evidence_detail String DEFAULT '',
    confidence Float64 DEFAULT 0.0,
    updated_at_ms UInt64
) ENGINE = ReplacingMergeTree(updated_at_ms)
PARTITION BY toYYYYMM(toDateTime(bucket_start))
ORDER BY (bucket_start, caller_service, target_service, evidence_type);

CREATE TABLE IF NOT EXISTS topology_api_edges_5m (
    bucket_start Int64,
    caller_service String,
    caller_api String DEFAULT '',
    target_service String,
    target_api String,
    request_count UInt64 DEFAULT 0,
    error_count UInt64 DEFAULT 0,
    http_4xx_count UInt64 DEFAULT 0,
    http_5xx_count UInt64 DEFAULT 0,
    timeout_count UInt64 DEFAULT 0,
    tcp_reset_count UInt64 DEFAULT 0,
    incomplete_count UInt64 DEFAULT 0,
    latency_sum Float64 DEFAULT 0.0,
    p50_latency_ms Float64 DEFAULT 0.0,
    p95_latency_ms Float64 DEFAULT 0.0,
    p99_latency_ms Float64 DEFAULT 0.0,
    request_bytes UInt64 DEFAULT 0,
    response_bytes UInt64 DEFAULT 0,
    unique_principals UInt64 DEFAULT 0,
    unique_source_ips UInt64 DEFAULT 0,
    anonymous_requests UInt64 DEFAULT 0,
    first_seen_ms UInt64 DEFAULT 0,
    last_seen_ms UInt64 DEFAULT 0,
    evidence_type LowCardinality(String) DEFAULT 'OTEL_CLIENT_SERVER',
    evidence_detail String DEFAULT '',
    confidence Float64 DEFAULT 0.0,
    updated_at_ms UInt64
) ENGINE = ReplacingMergeTree(updated_at_ms)
PARTITION BY toYYYYMM(toDateTime(bucket_start))
ORDER BY (bucket_start, caller_service, caller_api, target_service, target_api, evidence_type);

CREATE TABLE IF NOT EXISTS topology_principal_edges_5m (
    bucket_start Int64,
    principal String,
    caller_service String,
    caller_api String DEFAULT '',
    target_service String,
    target_api String,
    request_count UInt64 DEFAULT 0,
    error_count UInt64 DEFAULT 0,
    http_4xx_count UInt64 DEFAULT 0,
    http_5xx_count UInt64 DEFAULT 0,
    timeout_count UInt64 DEFAULT 0,
    tcp_reset_count UInt64 DEFAULT 0,
    incomplete_count UInt64 DEFAULT 0,
    latency_sum Float64 DEFAULT 0.0,
    p50_latency_ms Float64 DEFAULT 0.0,
    p95_latency_ms Float64 DEFAULT 0.0,
    p99_latency_ms Float64 DEFAULT 0.0,
    request_bytes UInt64 DEFAULT 0,
    response_bytes UInt64 DEFAULT 0,
    unique_principals UInt64 DEFAULT 0,
    unique_source_ips UInt64 DEFAULT 0,
    anonymous_requests UInt64 DEFAULT 0,
    first_seen_ms UInt64 DEFAULT 0,
    last_seen_ms UInt64 DEFAULT 0,
    evidence_type LowCardinality(String) DEFAULT 'OTEL_CLIENT_SERVER',
    evidence_detail String DEFAULT '',
    confidence Float64 DEFAULT 0.0,
    updated_at_ms UInt64
) ENGINE = ReplacingMergeTree(updated_at_ms)
PARTITION BY toYYYYMM(toDateTime(bucket_start))
ORDER BY (bucket_start, principal, caller_service, caller_api, target_service, target_api, evidence_type);

ALTER TABLE topology_principal_edges_5m ADD COLUMN IF NOT EXISTS unique_principals UInt64 DEFAULT 0 AFTER response_bytes;

CREATE TABLE IF NOT EXISTS topology_principal_ip_5m (
    bucket_start Int64,
    principal String,
    source_ip String,
    service String,
    api String,
    caller_service String DEFAULT '',
    request_count UInt64 DEFAULT 0,
    error_count UInt64 DEFAULT 0,
    http_4xx_count UInt64 DEFAULT 0,
    http_5xx_count UInt64 DEFAULT 0,
    timeout_count UInt64 DEFAULT 0,
    p95_latency_ms Float64 DEFAULT 0.0,
    request_bytes UInt64 DEFAULT 0,
    response_bytes UInt64 DEFAULT 0,
    first_seen_ms UInt64 DEFAULT 0,
    last_seen_ms UInt64 DEFAULT 0,
    is_load_balancer UInt8 DEFAULT 0,
    source_ip_role LowCardinality(String) DEFAULT 'unknown',
    role_label String DEFAULT 'Unknown source',
    attribution_confidence LowCardinality(String) DEFAULT 'low',
    is_new_ip UInt8 DEFAULT 0,
    updated_at_ms UInt64
) ENGINE = ReplacingMergeTree(updated_at_ms)
PARTITION BY toYYYYMM(toDateTime(bucket_start))
ORDER BY (bucket_start, principal, source_ip, service, api, caller_service);

-- Current tables are latest-row indexes for fast point-in-time reads. The
-- historical five-minute tables remain the source for comparisons and trends.
CREATE TABLE IF NOT EXISTS topology_service_current AS topology_service_edges_5m
ENGINE = ReplacingMergeTree(updated_at_ms)
ORDER BY (caller_service, target_service, evidence_type);

CREATE TABLE IF NOT EXISTS topology_api_current AS topology_api_edges_5m
ENGINE = ReplacingMergeTree(updated_at_ms)
ORDER BY (caller_service, caller_api, target_service, target_api, evidence_type);

CREATE TABLE IF NOT EXISTS topology_principal_current AS topology_principal_edges_5m
ENGINE = ReplacingMergeTree(updated_at_ms)
ORDER BY (principal, caller_service, caller_api, target_service, target_api, evidence_type);

CREATE TABLE IF NOT EXISTS topology_principal_ip_current AS topology_principal_ip_5m
ENGINE = ReplacingMergeTree(updated_at_ms)
ORDER BY (principal, source_ip, service, api, caller_service);
