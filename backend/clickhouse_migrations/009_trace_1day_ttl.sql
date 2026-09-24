-- ClickHouse Schema Migration 009: 1-day TTL for ClickHouse trace data.
--
-- Since Elasticsearch retains full distributed trace spans and waterfalls,
-- ClickHouse traces copied for worker SQL calculations expire after 1 day.

ALTER TABLE traces MODIFY TTL toDateTime(intDiv(timestamp_ms, 1000)) + toIntervalDay(1);
