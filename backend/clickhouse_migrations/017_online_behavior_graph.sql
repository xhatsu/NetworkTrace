-- Durable online graph states. Publication uses the behavior source snapshot pointer.
CREATE TABLE IF NOT EXISTS behavior_graph_models (
 source LowCardinality(String), version String, data_json String, updated_at UInt64
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (source,version)
TTL toDateTime(intDiv(updated_at,1000000)) + INTERVAL 7 DAY;
