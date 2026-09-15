-- ClickHouse Schema Migration 006: compact principal readiness history.
--
-- Detector readiness previously regrouped the retained traces table for every
-- principal-processing page. Aggregate states preserve the exact four inputs
-- used by evaluate_readiness_from_stats while reducing reads to principal-sized
-- summary rows. The view deliberately does not use POPULATE: ClickHouse rejects
-- POPULATE together with TO, and fresh deployments start with an empty database.
-- Existing-data backfills must be run as a separately controlled operation.

CREATE TABLE IF NOT EXISTS principal_readiness_summary (
    principal_id String,
    first_seen_state AggregateFunction(min, Int64),
    last_seen_state AggregateFunction(max, Int64),
    active_days_state AggregateFunction(uniqExact, Int64),
    observation_count_state AggregateFunction(count)
) ENGINE = AggregatingMergeTree()
ORDER BY principal_id;

CREATE MATERIALIZED VIEW IF NOT EXISTS principal_readiness_summary_mv
TO principal_readiness_summary AS
SELECT
    principal_key AS principal_id,
    minState(timestamp_ms) AS first_seen_state,
    maxState(timestamp_ms) AS last_seen_state,
    uniqExactState(toInt64(intDiv(timestamp_ms, 86400000))) AS active_days_state,
    countState() AS observation_count_state
FROM (
    SELECT
        ifNull(principal_id, concat(if(service_environment = '', 'production', service_environment), ':', principal_name)) AS principal_key,
        timestamp_ms
    FROM traces
    WHERE principal_name NOT IN ('', 'unknown')
)
GROUP BY principal_key;
