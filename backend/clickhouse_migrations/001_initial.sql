-- ClickHouse Schema Migration 001: Initial Complete Schema
-- Defines all TraceScope tables using native ClickHouse engines, partitioning, and sorting keys.
-- ClickHouse is the sole live persistence layer: raw evidence and all derived
-- views share one store, preventing dashboard/anomaly disagreement during ingest.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version String,
    applied_at_ms UInt64
) ENGINE = ReplacingMergeTree(applied_at_ms)
ORDER BY (version);

-- Raw traces retain sanitized evidence. Partitioning by time keeps retention and range scans bounded.
CREATE TABLE IF NOT EXISTS traces (
    id UInt64 DEFAULT toUnixTimestamp64Micro(now64(6)),
    event_uid LowCardinality(String),
    timestamp Int64,
    timestamp_ms Int64,
    trace_id String,
    span_id String,
    parent_span_id Nullable(String),
    service_name LowCardinality(String),
    service_instance Nullable(String),
    service_environment LowCardinality(String) DEFAULT 'production',
    caller_service Nullable(String),
    caller_instance Nullable(String),
    caller_ip Nullable(String),
    target_service LowCardinality(String),
    target_instance Nullable(String),
    target_ip Nullable(String),
    target_port Nullable(UInt16),
    principal_name LowCardinality(String) DEFAULT 'unknown',
    operation String,
    http_method LowCardinality(Nullable(String)),
    http_route Nullable(String),
    http_status Nullable(UInt16),
    status_class LowCardinality(Nullable(String)),
    duration_ms Float64,
    duration_us UInt64,
    outcome LowCardinality(Nullable(String)),
    protocol LowCardinality(String) DEFAULT 'http',
    span_kind LowCardinality(String) DEFAULT 'server',
    attributes_json String DEFAULT '{}',
    created_at UInt64,
    environment LowCardinality(String) DEFAULT 'production',
    principal_id Nullable(String),
    identity_source LowCardinality(String) DEFAULT 'unknown',
    auth_result LowCardinality(String) DEFAULT 'unknown',
    auth_evidence LowCardinality(String) DEFAULT 'unknown',
    caller_resolution_method LowCardinality(String) DEFAULT 'none',
    caller_confidence Float32 DEFAULT 0.0,
    network_peer_ip Nullable(String),
    original_client_ip Nullable(String),
    original_client_ip_trusted UInt8 DEFAULT 0,
    source_group Nullable(String),
    operation_key Nullable(String),
    soap_fault_code Nullable(String),
    outcome_class LowCardinality(String) DEFAULT 'unknown',
    sampling_context Nullable(String),
    dedup_key Nullable(String),
    INDEX idx_traces_principal principal_name TYPE set(100) GRANULARITY 1
) ENGINE = ReplacingMergeTree(created_at)
PARTITION BY toYYYYMM(toDateTime(intDiv(timestamp_ms, 1000)))
ORDER BY (service_name, timestamp_ms, trace_id, span_id);

-- Materialized rollups shield interactive dashboards from scanning high-volume trace rows.
CREATE TABLE IF NOT EXISTS metric_buckets (
    id UInt64 DEFAULT toUnixTimestamp64Micro(now64(6)),
    bucket_start Int64,
    bucket_size UInt32,
    caller_service String DEFAULT '',
    target_service String DEFAULT '',
    principal_name String DEFAULT '',
    operation String DEFAULT '',
    request_count UInt64 DEFAULT 0,
    error_count UInt64 DEFAULT 0,
    latency_sum Float64 DEFAULT 0.0,
    latency_avg Float64 DEFAULT 0.0,
    latency_min Float64 DEFAULT 0.0,
    latency_max Float64 DEFAULT 0.0,
    latency_p50 Float64 DEFAULT 0.0,
    latency_p95 Float64 DEFAULT 0.0,
    latency_p99 Float64 DEFAULT 0.0,
    created_at UInt64
) ENGINE = ReplacingMergeTree(created_at)
PARTITION BY toYYYYMM(toDateTime(bucket_start))
ORDER BY (bucket_size, bucket_start, caller_service, target_service, principal_name, operation);

-- Dependency tables make topology and blast-radius queries predictable rather than recursive raw scans.
CREATE TABLE IF NOT EXISTS service_edges (
    caller_service String,
    target_service String,
    first_seen UInt64,
    last_seen UInt64,
    request_count UInt64 DEFAULT 0,
    error_count UInt64 DEFAULT 0,
    error_rate Float64 DEFAULT 0.0,
    avg_latency Float64 DEFAULT 0.0,
    p95_latency Float64 DEFAULT 0.0,
    principal_count UInt32 DEFAULT 0,
    operation_count UInt32 DEFAULT 0
) ENGINE = ReplacingMergeTree(last_seen)
ORDER BY (caller_service, target_service);

CREATE TABLE IF NOT EXISTS principal_service_edges (
    principal_name String,
    caller_service String,
    target_service String,
    first_seen UInt64,
    last_seen UInt64,
    request_count UInt64 DEFAULT 0,
    error_rate Float64 DEFAULT 0.0,
    p95_latency Float64 DEFAULT 0.0
) ENGINE = ReplacingMergeTree(last_seen)
ORDER BY (principal_name, caller_service, target_service);

-- Robust baselines are stored separately so detector expectations survive worker restarts.
CREATE TABLE IF NOT EXISTS baseline_metrics (
    id UInt64 DEFAULT 0,
    dimension_type String,
    dimension_key String,
    hour_of_day UInt8,
    day_of_week UInt8,
    sample_count UInt32 DEFAULT 0,
    rps_median Float64 DEFAULT 0.0,
    rps_mad Float64 DEFAULT 0.0,
    latency_p50_median Float64 DEFAULT 0.0,
    latency_p95_median Float64 DEFAULT 0.0,
    latency_p95_mad Float64 DEFAULT 0.0,
    error_rate_median Float64 DEFAULT 0.0,
    error_rate_mad Float64 DEFAULT 0.0,
    updated_at UInt64
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (dimension_type, dimension_key, hour_of_day, day_of_week);

-- Immutable anomaly observations stay distinct from operator-managed incident state.
CREATE TABLE IF NOT EXISTS anomaly_events (
    id UInt64 DEFAULT toUnixTimestamp64Micro(now64(6)),
    detected_at UInt64,
    anomaly_type String,
    severity LowCardinality(String),
    score UInt32,
    confidence Float32 DEFAULT 1.0,
    caller_service Nullable(String),
    target_service Nullable(String),
    principal_name Nullable(String),
    source_ip Nullable(String),
    operation Nullable(String),
    instance Nullable(String),
    baseline_value Nullable(Float64),
    current_value Nullable(Float64),
    delta_percentage Nullable(Float64),
    first_seen Nullable(UInt64),
    last_seen Nullable(UInt64),
    status LowCardinality(String) DEFAULT 'open',
    acknowledged UInt8 DEFAULT 0,
    reason_json String DEFAULT '[]',
    metadata_json String DEFAULT '{}'
) ENGINE = ReplacingMergeTree()
ORDER BY (id);

-- Identity-derived relations hold normalized behavior, never reusable authentication material.
CREATE TABLE IF NOT EXISTS principals (
    id UInt64 DEFAULT 0,
    principal_name String,
    principal_type LowCardinality(String) DEFAULT 'unknown',
    first_seen UInt64,
    last_seen UInt64,
    total_requests UInt64 DEFAULT 0,
    unique_callers UInt32 DEFAULT 0,
    unique_sources UInt32 DEFAULT 0,
    unique_targets UInt32 DEFAULT 0,
    unique_operations UInt32 DEFAULT 0,
    created_at UInt64,
    updated_at UInt64
) ENGINE = ReplacingMergeTree()
ORDER BY (principal_name);

CREATE TABLE IF NOT EXISTS principal_callers (
    principal_name String,
    caller_service String,
    first_seen UInt64,
    last_seen UInt64,
    observation_count UInt64 DEFAULT 0
) ENGINE = ReplacingMergeTree(last_seen)
ORDER BY (principal_name, caller_service);

CREATE TABLE IF NOT EXISTS principal_sources (
    principal_name String,
    source_ip String,
    first_seen UInt64,
    last_seen UInt64,
    observation_count UInt64 DEFAULT 0
) ENGINE = ReplacingMergeTree(last_seen)
ORDER BY (principal_name, source_ip);

CREATE TABLE IF NOT EXISTS principal_targets (
    principal_name String,
    target_service String,
    first_seen UInt64,
    last_seen UInt64,
    observation_count UInt64 DEFAULT 0,
    error_count UInt64 DEFAULT 0
) ENGINE = ReplacingMergeTree(last_seen)
ORDER BY (principal_name, target_service);

CREATE TABLE IF NOT EXISTS principal_operations (
    principal_name String,
    target_service String,
    operation String,
    first_seen UInt64,
    last_seen UInt64,
    observation_count UInt64 DEFAULT 0,
    error_count UInt64 DEFAULT 0
) ENGINE = ReplacingMergeTree(last_seen)
ORDER BY (principal_name, target_service, operation);

CREATE TABLE IF NOT EXISTS principal_relationships (
    id UInt64 DEFAULT 0,
    principal_name String,
    caller_service String DEFAULT '',
    caller_instance String DEFAULT '',
    source_ip String DEFAULT '',
    target_service String,
    target_instance String DEFAULT '',
    target_ip String DEFAULT '',
    target_port UInt16 DEFAULT 0,
    operation String,
    http_method String DEFAULT '',
    first_seen UInt64,
    last_seen UInt64,
    observation_count UInt64 DEFAULT 0,
    success_count UInt64 DEFAULT 0,
    error_count UInt64 DEFAULT 0
) ENGINE = ReplacingMergeTree(last_seen)
ORDER BY (principal_name, caller_service, caller_instance, source_ip, target_service, target_instance, target_ip, target_port, operation, http_method);

CREATE TABLE IF NOT EXISTS principal_hourly_activity (
    principal_name String,
    day_of_week UInt8,
    hour_of_day UInt8,
    observation_count UInt64 DEFAULT 0,
    error_count UInt64 DEFAULT 0
) ENGINE = ReplacingMergeTree(observation_count)
ORDER BY (principal_name, day_of_week, hour_of_day);

CREATE TABLE IF NOT EXISTS principal_daily_stats (
    principal_name String,
    day_start UInt64,
    observation_count UInt64 DEFAULT 0,
    error_count UInt64 DEFAULT 0,
    unique_callers UInt32 DEFAULT 0,
    unique_sources UInt32 DEFAULT 0,
    unique_targets UInt32 DEFAULT 0,
    unique_operations UInt32 DEFAULT 0
) ENGINE = ReplacingMergeTree(observation_count)
ORDER BY (principal_name, day_start);

CREATE TABLE IF NOT EXISTS principal_baselines (
    principal_name String,
    dimension_type String,
    dimension_value String,
    first_seen UInt64,
    last_seen UInt64,
    observation_count UInt64 DEFAULT 0,
    distribution_share Float64 DEFAULT 0.0
) ENGINE = ReplacingMergeTree(last_seen)
ORDER BY (principal_name, dimension_type, dimension_value);

CREATE TABLE IF NOT EXISTS principal_change_events (
    id UInt64 DEFAULT toUnixTimestamp64Micro(now64(6)),
    fingerprint String,
    principal_name String,
    change_type String,
    severity LowCardinality(String),
    score UInt32,
    detected_at UInt64,
    caller_service Nullable(String),
    source_ip Nullable(String),
    target_service Nullable(String),
    operation Nullable(String),
    old_value Nullable(String),
    new_value Nullable(String),
    first_observed UInt64,
    reason_json String DEFAULT '{}',
    status LowCardinality(String) DEFAULT 'new',
    updated_at UInt64,
    incident_id Nullable(String),
    principal_id Nullable(String),
    environment LowCardinality(String) DEFAULT 'production',
    base_importance Nullable(String),
    category LowCardinality(String) DEFAULT 'behavioral',
    family Nullable(String),
    reliability Nullable(String),
    review_reason Nullable(String),
    reviewed_by Nullable(String),
    expires_at Nullable(UInt64)
) ENGINE = ReplacingMergeTree()
ORDER BY (fingerprint);

-- Latest and history tables separate fleet-health reads from bounded forensic retention.
CREATE TABLE IF NOT EXISTS agent_stats_latest (
    node String,
    instance_id String,
    sequence UInt64,
    observed_at UInt64,
    window_seconds UInt32,
    mode Nullable(String),
    status LowCardinality(String),
    reasons_json String DEFAULT '[]',
    cap_packets_total Nullable(Int64),
    cap_packets_delta Nullable(Int64),
    cap_packet_bytes_total Nullable(Int64),
    cap_packet_bytes_delta Nullable(Int64),
    cap_kernel_drops_total Nullable(Int64),
    cap_kernel_drops_delta Nullable(Int64),
    cap_kernel_drop_percent Nullable(Float64),
    cap_invalid_frames_total Nullable(Int64),
    cap_events_emitted_total Nullable(Int64),
    cap_events_emitted_delta Nullable(Int64),
    cap_flows_active Nullable(Int64),
    cap_pending_requests Nullable(Int64),
    cap_wsse_body_flows_active Nullable(Int64),
    ship_events_in_total Nullable(Int64),
    ship_events_in_delta Nullable(Int64),
    ship_events_pushed_total Nullable(Int64),
    ship_events_pushed_delta Nullable(Int64),
    ship_events_dropped_total Nullable(Int64),
    ship_events_dropped_delta Nullable(Int64),
    ship_drop_causes_json Nullable(String),
    ship_batches_pushed_total Nullable(Int64),
    ship_batches_pushed_delta Nullable(Int64),
    ship_batches_failed_total Nullable(Int64),
    ship_batches_failed_delta Nullable(Int64),
    ship_bytes_pushed_total Nullable(Int64),
    ship_bytes_pushed_delta Nullable(Int64),
    ship_push_events_per_second Nullable(Float64),
    ship_push_kbps Nullable(Float64),
    ship_drop_events_per_second Nullable(Float64),
    ship_drop_percent Nullable(Float64),
    ship_queue_depth_events Nullable(Int64),
    ship_queue_capacity_events Nullable(Int64),
    ship_queue_high_water_events Nullable(Int64),
    ship_last_push_http_status Nullable(Int32),
    ship_last_success_at Nullable(Int64),
    ship_consecutive_failures Nullable(Int32),
    ship_stats_samples_dropped_total Nullable(Int64),
    res_cpu_user_seconds Nullable(Float64),
    res_cpu_system_seconds Nullable(Float64),
    res_cpu_percent_one_core Nullable(Float64),
    res_rss_bytes Nullable(Int64),
    res_virtual_bytes Nullable(Int64),
    res_open_fds Nullable(Int32),
    res_threads Nullable(Int32),
    lim_cpu_core Nullable(Int32),
    lim_address_space_bytes Nullable(Int64),
    lim_ship_rate_kbps Nullable(Int32),
    lim_http_body_max_bytes Nullable(Int32),
    lim_ship_threads_max Nullable(Int32),
    lim_wsse_body_bytes Nullable(Int32),
    raw_json String,
    ingested_at UInt64
) ENGINE = ReplacingMergeTree(ingested_at)
ORDER BY (node, instance_id);

CREATE TABLE IF NOT EXISTS agent_stats_history (
    node String,
    instance_id String,
    sequence UInt64,
    observed_at UInt64,
    window_seconds UInt32,
    mode Nullable(String),
    status LowCardinality(String),
    reasons_json String DEFAULT '[]',
    raw_json String,
    ingested_at UInt64
) ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(toDateTime(observed_at))
ORDER BY (node, instance_id, sequence);

-- Batch IDs provide replay safety when a shipper retries after a lost response.
CREATE TABLE IF NOT EXISTS ingest_batches (
    batch_id String,
    node Nullable(String),
    record_count UInt64 DEFAULT 0,
    received_at_ms UInt64,
    status LowCardinality(String) DEFAULT 'accepted'
) ENGINE = ReplacingMergeTree(received_at_ms)
ORDER BY (batch_id)
TTL toDateTime(intDiv(received_at_ms, 1000)) + INTERVAL 7 DAY;

-- Incident and behavioral state use versioned rows because ClickHouse mutations are not row locks.
CREATE TABLE IF NOT EXISTS incidents (
    incident_id String,
    principal_id String,
    environment LowCardinality(String) DEFAULT 'production',
    category LowCardinality(String),
    scope String,
    started_at UInt64,
    last_seen_at UInt64,
    closed_at Nullable(UInt64),
    status LowCardinality(String) DEFAULT 'open',
    score UInt32 DEFAULT 0,
    priority LowCardinality(String) DEFAULT 'low',
    confidence Float32 DEFAULT 1.0,
    family_scores_json String DEFAULT '{}',
    contributing_event_ids_json String DEFAULT '[]',
    suppressed_contributions_json String DEFAULT '[]',
    successor_id Nullable(String),
    review_notes Nullable(String),
    reviewed_by Nullable(String),
    reviewed_at Nullable(UInt64),
    created_at UInt64,
    updated_at UInt64
) ENGINE = ReplacingMergeTree()
ORDER BY (incident_id);

CREATE TABLE IF NOT EXISTS historical_registry (
    registry_key String,
    principal_id String,
    dimension_type String,
    dimension_value String,
    first_seen UInt64,
    last_seen UInt64,
    observation_count UInt64 DEFAULT 0,
    created_at UInt64,
    updated_at UInt64
) ENGINE = ReplacingMergeTree()
ORDER BY (registry_key);

CREATE TABLE IF NOT EXISTS established_baselines (
    baseline_key String,
    principal_id String,
    dimension_type String,
    dimension_value String,
    first_seen UInt64,
    last_seen UInt64,
    observation_count UInt64 DEFAULT 0,
    distribution_share Float64 DEFAULT 0.0,
    promoted_at UInt64,
    promotion_reason String,
    created_at UInt64,
    updated_at UInt64
) ENGINE = ReplacingMergeTree()
ORDER BY (baseline_key);

CREATE TABLE IF NOT EXISTS candidate_behaviors (
    candidate_key String,
    principal_id String,
    dimension_type String,
    dimension_value String,
    first_seen UInt64,
    last_seen UInt64,
    distinct_days_count UInt32 DEFAULT 1,
    distinct_windows_count UInt32 DEFAULT 1,
    observation_count UInt64 DEFAULT 1,
    status LowCardinality(String) DEFAULT 'pending',
    created_at UInt64,
    updated_at UInt64
) ENGINE = ReplacingMergeTree()
ORDER BY (candidate_key);

CREATE TABLE IF NOT EXISTS operator_overrides (
    id UInt64,
    scope_type String,
    scope_value String,
    reason String,
    operator String,
    created_at UInt64,
    expires_at Nullable(UInt64)
) ENGINE = ReplacingMergeTree(created_at)
ORDER BY (scope_type, scope_value, id);

-- Quality windows prevent detectors from treating known incomplete telemetry as behavioral change.
CREATE TABLE IF NOT EXISTS telemetry_quality_windows (
    window_start_sec UInt32,
    window_end_sec UInt32,
    total_spans UInt64 DEFAULT 0,
    counted_requests UInt64 DEFAULT 0,
    caller_linked_count UInt64 DEFAULT 0,
    caller_linkage_rate Float64 DEFAULT 0.0,
    username_extracted_count UInt64 DEFAULT 0,
    username_extraction_rate Float64 DEFAULT 0.0,
    is_collection_gap UInt8 DEFAULT 0,
    sampling_ratio Float64 DEFAULT 1.0,
    created_at UInt64
) ENGINE = ReplacingMergeTree(created_at)
ORDER BY (window_start_sec);

CREATE TABLE IF NOT EXISTS checkpoints (
    source String,
    cursor_json String DEFAULT '{}',
    updated_at_ms UInt64
) ENGINE = ReplacingMergeTree()
ORDER BY (source);

CREATE TABLE IF NOT EXISTS jobs (
    name String,
    status LowCardinality(String),
    started_at_ms UInt64 DEFAULT 0,
    finished_at_ms Nullable(UInt64),
    detail String DEFAULT '',
    processed_count UInt64 DEFAULT 0
) ENGINE = ReplacingMergeTree()
ORDER BY (name);

-- Legacy-compatible analytical tables remain in the same store during API contract migration.
CREATE TABLE IF NOT EXISTS services (
    name String,
    environment LowCardinality(String) DEFAULT 'production',
    service_group Nullable(String),
    service_module Nullable(String),
    first_seen_ms UInt64,
    last_seen_ms UInt64
) ENGINE = ReplacingMergeTree()
ORDER BY (name);

CREATE TABLE IF NOT EXISTS accounts (
    username String,
    namespace String DEFAULT '',
    first_seen_ms UInt64,
    last_seen_ms UInt64
) ENGINE = ReplacingMergeTree()
ORDER BY (username, namespace);

CREATE TABLE IF NOT EXISTS latency_rollups (
    bucket_ms UInt64,
    bucket_seconds UInt32 DEFAULT 60,
    service_name String,
    operation String DEFAULT '',
    account_username String DEFAULT '',
    environment String DEFAULT '',
    request_count UInt64 DEFAULT 0,
    server_count UInt64 DEFAULT 0,
    http_count UInt64 DEFAULT 0,
    duration_sum_us UInt64 DEFAULT 0,
    histogram_json String DEFAULT '{}',
    status_2xx UInt64 DEFAULT 0,
    status_4xx UInt64 DEFAULT 0,
    status_5xx UInt64 DEFAULT 0,
    denied_count UInt64 DEFAULT 0,
    slow_count UInt64 DEFAULT 0,
    success_count UInt64 DEFAULT 0,
    failure_count UInt64 DEFAULT 0,
    unknown_count UInt64 DEFAULT 0,
    sampled_count UInt64 DEFAULT 0,
    unsampled_count UInt64 DEFAULT 0,
    updated_at_ms UInt64
) ENGINE = ReplacingMergeTree()
PARTITION BY toYYYYMM(toDateTime(intDiv(bucket_ms, 1000)))
ORDER BY (bucket_ms, service_name, operation, account_username, environment);

CREATE TABLE IF NOT EXISTS topology_edges (
    bucket_ms UInt64,
    source_service String,
    target_service String,
    evidence LowCardinality(String),
    evidence_detail String DEFAULT '',
    request_count UInt64 DEFAULT 0,
    duration_sum_us UInt64 DEFAULT 0,
    failure_count UInt64 DEFAULT 0,
    histogram_json String DEFAULT '{}',
    updated_at_ms UInt64
) ENGINE = ReplacingMergeTree()
ORDER BY (bucket_ms, source_service, target_service, evidence);

CREATE TABLE IF NOT EXISTS events (
    event_uid String,
    timestamp_ms Int64,
    ingested_ms Nullable(Int64),
    trace_id Nullable(String),
    transaction_id Nullable(String),
    parent_id Nullable(String),
    service_name String,
    environment Nullable(String),
    node_name Nullable(String),
    service_group Nullable(String),
    service_module Nullable(String),
    operation String,
    duration_us UInt64,
    sampled Nullable(UInt8),
    outcome Nullable(String),
    http_method Nullable(String),
    status_code Nullable(UInt16),
    account_username Nullable(String),
    account_namespace Nullable(String),
    span_kind String DEFAULT 'server',
    event_type String DEFAULT 'span',
    peer_service Nullable(String),
    peer_address Nullable(String),
    host_address Nullable(String),
    url_domain Nullable(String),
    url_port Nullable(UInt16),
    url_path Nullable(String),
    source_file Nullable(String),
    source_offset Nullable(Int64),
    created_at_ms UInt64,
    client_ip Nullable(String),
    source_ip Nullable(String),
    attributes_json Nullable(String)
) ENGINE = ReplacingMergeTree()
PARTITION BY toYYYYMM(toDateTime(intDiv(timestamp_ms, 1000)))
ORDER BY (service_name, timestamp_ms, event_uid);

CREATE TABLE IF NOT EXISTS anomalies (
    id UInt64,
    fingerprint String,
    entity_type String,
    entity_id String,
    anomaly_type String,
    first_detected_ms UInt64,
    last_detected_ms UInt64,
    window_start_ms UInt64,
    window_end_ms UInt64,
    current_value Float64,
    baseline_value Nullable(Float64),
    normal_low Nullable(Float64),
    normal_high Nullable(Float64),
    absolute_difference Float64,
    percent_change Nullable(Float64),
    current_samples UInt32,
    baseline_samples UInt32,
    persistence_buckets UInt32,
    severity LowCardinality(String),
    status LowCardinality(String) DEFAULT 'open',
    suppressed_until_ms Nullable(UInt64),
    unit String,
    explanation String,
    rule String,
    training_start_ms Nullable(UInt64),
    training_end_ms Nullable(UInt64),
    limitations_json String DEFAULT '[]',
    contributors_json String DEFAULT '[]',
    trace_ids_json String DEFAULT '[]',
    updated_at_ms UInt64
) ENGINE = ReplacingMergeTree()
ORDER BY (fingerprint);

CREATE TABLE IF NOT EXISTS anomaly_occurrences (
    id UInt64,
    anomaly_id UInt64,
    start_ms UInt64,
    end_ms UInt64,
    value Float64,
    created_at_ms UInt64
) ENGINE = MergeTree()
ORDER BY (anomaly_id, start_ms);

CREATE TABLE IF NOT EXISTS address_mappings (
    address String,
    service_name String,
    valid_from_ms Int64,
    valid_to_ms Nullable(Int64),
    source String,
    confidence Float32 DEFAULT 1.0
) ENGINE = ReplacingMergeTree()
ORDER BY (address, service_name, valid_from_ms);

CREATE TABLE IF NOT EXISTS dirty_buckets (
    bucket_ms Int64,
    reason String,
    created_at_ms Int64
) ENGINE = ReplacingMergeTree()
ORDER BY (bucket_ms);
