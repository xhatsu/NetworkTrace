-- ClickHouse Schema Migration 004: live table retention TTLs.
--
-- Applies live-table retention to align schema reality with chart config.retentionDays: 30:
--   - raw traces: 30 days based on timestamp_ms
--   - metric_buckets: fixed 90 days based on bucket_start
-- Note: agent_stats_history 1-day TTL was applied in migration 002;
--       metric_buckets_agg 90-day TTL was applied in migration 003.

ALTER TABLE traces MODIFY TTL toDateTime(intDiv(timestamp_ms, 1000)) + INTERVAL 30 DAY DELETE;
ALTER TABLE metric_buckets MODIFY TTL toDateTime(bucket_start) + INTERVAL 90 DAY DELETE;
