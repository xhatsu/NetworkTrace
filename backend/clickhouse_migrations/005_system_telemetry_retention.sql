-- ClickHouse Schema Migration 005: system telemetry retention TTLs.
--
-- Restricts unbounded internal ClickHouse log expansion:
--   - text_log, query_log, processors_profile_log, part_log, trace_log,
--     metric_log, asynchronous_metric_log, error_log: 1 day TTL

ALTER TABLE system.text_log MODIFY TTL event_date + toIntervalDay(1);
ALTER TABLE system.query_log MODIFY TTL event_date + toIntervalDay(1);
ALTER TABLE system.processors_profile_log MODIFY TTL event_date + toIntervalDay(1);
ALTER TABLE system.part_log MODIFY TTL event_date + toIntervalDay(1);
ALTER TABLE system.trace_log MODIFY TTL event_date + toIntervalDay(1);
ALTER TABLE system.metric_log MODIFY TTL event_date + toIntervalDay(1);
ALTER TABLE system.asynchronous_metric_log MODIFY TTL event_date + toIntervalDay(1);
ALTER TABLE system.error_log MODIFY TTL event_date + toIntervalDay(1);
