-- ClickHouse Schema Migration 002: durable identifiers, ingest recovery, and bounded agent history.

ALTER TABLE traces ADD COLUMN IF NOT EXISTS row_uid UUID DEFAULT generateUUIDv4();
ALTER TABLE traces ADD COLUMN IF NOT EXISTS ingest_order UInt64 DEFAULT toUnixTimestamp64Nano(now64(9));
ALTER TABLE traces ADD COLUMN IF NOT EXISTS ingest_batch_id String DEFAULT '';
ALTER TABLE traces MATERIALIZE COLUMN row_uid;
ALTER TABLE traces MATERIALIZE COLUMN ingest_order;
ALTER TABLE traces MODIFY COLUMN id UInt64 DEFAULT sipHash64(generateUUIDv4());
ALTER TABLE traces UPDATE id = sipHash64(row_uid) WHERE 1 SETTINGS mutations_sync = 1;

CREATE TABLE IF NOT EXISTS anomaly_events_v2 AS anomaly_events;
ALTER TABLE anomaly_events_v2 MODIFY COLUMN id UInt64 DEFAULT sipHash64(generateUUIDv4());
TRUNCATE TABLE anomaly_events_v2;
INSERT INTO anomaly_events_v2 (
    detected_at, anomaly_type, severity, score, confidence, caller_service,
    target_service, principal_name, source_ip, operation, instance,
    baseline_value, current_value, delta_percentage, first_seen, last_seen,
    status, acknowledged, reason_json, metadata_json
)
SELECT
    detected_at, anomaly_type, severity, score, confidence, caller_service,
    target_service, principal_name, source_ip, operation, instance,
    baseline_value, current_value, delta_percentage, first_seen, last_seen,
    status, acknowledged, reason_json, metadata_json
FROM anomaly_events;
DROP TABLE IF EXISTS anomaly_events_pre_v2;
RENAME TABLE anomaly_events TO anomaly_events_pre_v2, anomaly_events_v2 TO anomaly_events;
DROP TABLE anomaly_events_pre_v2;

ALTER TABLE agent_stats_history MODIFY TTL toDateTime(observed_at) + INTERVAL 1 DAY DELETE;

CREATE TABLE IF NOT EXISTS security_policy (
    policy_key String,
    policy_json String,
    updated_at UInt64
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY policy_key;
