-- ClickHouse Schema Migration 003: mergeable aggregate states in a shadow table.
--
-- Measured retention proposal (operator deploy decision for live tables):
--   raw traces: 30 days, metric buckets: 90 days, agent history: 1 day.
-- Migration 002 already applies the 1-day agent_stats_history TTL.  The live
-- traces and metric_buckets TTL statements are intentionally provided below as
-- comments and are NOT applied by this migration while cutover remains disabled:
-- ALTER TABLE traces MODIFY TTL toDateTime(intDiv(timestamp_ms, 1000)) + INTERVAL 30 DAY DELETE;
-- ALTER TABLE metric_buckets MODIFY TTL toDateTime(bucket_start) + INTERVAL 90 DAY DELETE;

CREATE TABLE IF NOT EXISTS metric_buckets_agg (
    bucket_start Int64,
    bucket_size UInt32,
    caller_service String DEFAULT '',
    target_service String DEFAULT '',
    principal_name String DEFAULT '',
    operation String DEFAULT '',
    request_count_state AggregateFunction(sum, UInt64),
    error_count_state AggregateFunction(countIf, UInt8),
    latency_sum_state AggregateFunction(sum, Float64),
    latency_quantiles_state AggregateFunction(quantilesTDigest(0.5, 0.95, 0.99), Float64),
    bucket_time DateTime MATERIALIZED toDateTime(bucket_start)
) ENGINE = AggregatingMergeTree()
PARTITION BY toYYYYMM(bucket_time)
ORDER BY (bucket_size, bucket_start, caller_service, target_service, principal_name, operation)
TTL bucket_time + INTERVAL 90 DAY DELETE;
