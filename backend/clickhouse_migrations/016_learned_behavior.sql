-- Shadow behavioral memory. Completed generations are the visibility boundary.
CREATE TABLE IF NOT EXISTS behavior_observations (
 source LowCardinality(String), day Int64, generation String, relationship_id String,
 bucket_ms Int64, data_json String, updated_at UInt64
) ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(toDateTime(intDiv(day,1000)))
ORDER BY (source,day,generation,relationship_id,bucket_ms)
TTL toDateTime(intDiv(day,1000)) + INTERVAL 30 DAY;
CREATE TABLE IF NOT EXISTS behavior_daily (
 source LowCardinality(String), day Int64, generation String, relationship_id String,
 data_json String, updated_at UInt64
) ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(toDateTime(intDiv(day,1000)))
ORDER BY (source,day,generation,relationship_id)
TTL toDateTime(intDiv(day,1000)) + INTERVAL 90 DAY;
CREATE TABLE IF NOT EXISTS behavior_windows (
 source LowCardinality(String), day Int64, generation String, data_json String, updated_at UInt64
) ENGINE = ReplacingMergeTree(updated_at) ORDER BY (source,day)
TTL toDateTime(intDiv(day,1000)) + INTERVAL 90 DAY;
CREATE TABLE IF NOT EXISTS behavior_state (
 source String, data_json String, updated_at UInt64
) ENGINE = ReplacingMergeTree(updated_at) ORDER BY source;
CREATE TABLE IF NOT EXISTS behavior_profiles (
 source LowCardinality(String), generation String, relationship_id String, data_json String, updated_at UInt64
) ENGINE = ReplacingMergeTree(updated_at) ORDER BY (source,generation,relationship_id)
TTL toDateTime(intDiv(updated_at,1000000)) + INTERVAL 7 DAY;
CREATE TABLE IF NOT EXISTS behavior_deviations (
 source LowCardinality(String), generation String, id String, relationship_id String, data_json String, updated_at UInt64
) ENGINE = ReplacingMergeTree(updated_at) ORDER BY (source,generation,id)
TTL toDateTime(intDiv(updated_at,1000000)) + INTERVAL 7 DAY;
CREATE TABLE IF NOT EXISTS behavior_contracts (
 event_id String, relationship_id String, state String, reason String, reviewer String,
 effective_at_ms Int64, expires_at_ms Int64, previous_event_id String, created_at UInt64
) ENGINE = MergeTree ORDER BY (relationship_id,created_at,event_id);
