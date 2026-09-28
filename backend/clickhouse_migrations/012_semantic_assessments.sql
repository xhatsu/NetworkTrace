-- Provider-neutral L4 semantic assessments. Raw telemetry and provider bodies are not stored.
CREATE TABLE IF NOT EXISTS semantic_assessments (
    episode_key String,
    episode_version FixedString(64),
    assessment_version LowCardinality(String),
    provider LowCardinality(String),
    provider_model String,
    status LowCardinality(String),
    abnormal_probability Nullable(Float32),
    category LowCardinality(String),
    priority LowCardinality(String),
    summary String,
    supporting_signal_ids Array(String),
    caveats Array(String),
    input_digest FixedString(64),
    response_digest Nullable(FixedString(64)),
    evaluated_at_ms UInt64,
    created_at_ms UInt64,
    updated_at_ms UInt64
) ENGINE = ReplacingMergeTree(updated_at_ms)
ORDER BY (episode_key, episode_version, assessment_version)
