-- Durable alert outbox and delivery history. Payloads are immutable event envelopes.
CREATE TABLE IF NOT EXISTS alert_events (
    event_id String,
    rule_id String,
    fingerprint String,
    event_type LowCardinality(String),
    payload_json String,
    created_at_ms UInt64
) ENGINE = ReplacingMergeTree(created_at_ms)
ORDER BY event_id;

CREATE TABLE IF NOT EXISTS alert_deliveries (
    delivery_id String,
    event_id String,
    rule_id String,
    destination_type LowCardinality(String),
    destination_target String,
    status LowCardinality(String),
    attempts UInt16 DEFAULT 0,
    response_code Int32 DEFAULT 0,
    error String DEFAULT '',
    next_attempt_at_ms UInt64 DEFAULT 0,
    updated_at_ms UInt64
) ENGINE = ReplacingMergeTree(updated_at_ms)
ORDER BY delivery_id;
