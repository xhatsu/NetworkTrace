-- User-defined alert routing rules. Conditions are JSON so new dimensions remain backward compatible.
CREATE TABLE IF NOT EXISTS alert_rules (
    id String,
    name String,
    enabled UInt8 DEFAULT 1,
    severity LowCardinality(String) DEFAULT 'warning',
    condition_json String,
    destinations_json String DEFAULT '[]',
    cooldown_minutes UInt32 DEFAULT 30,
    created_at_ms UInt64,
    updated_at_ms UInt64
) ENGINE = ReplacingMergeTree(updated_at_ms)
ORDER BY id;
