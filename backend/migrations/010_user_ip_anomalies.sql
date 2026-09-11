-- Migration 010: Support user + source_ip behavioral anomaly dimensions
-- SQLite does not support ADD COLUMN IF NOT EXISTS in all versions, so we use a safe table migration script or ALTER TABLE.
-- However, SQLite ignores errors in executescript only if statements succeed, so we add source_ip column if missing.

ALTER TABLE anomaly_events ADD COLUMN source_ip TEXT;

CREATE INDEX IF NOT EXISTS idx_ae_source_ip ON anomaly_events(source_ip, detected_at);
CREATE INDEX IF NOT EXISTS idx_ae_user_source_ip ON anomaly_events(principal_name, source_ip, detected_at);
CREATE INDEX IF NOT EXISTS idx_traces_caller_ip_ts ON traces(caller_ip, timestamp_ms);
CREATE INDEX IF NOT EXISTS idx_traces_user_ip_ts ON traces(principal_name, caller_ip, timestamp_ms);
