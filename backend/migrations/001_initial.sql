PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS events (
  event_uid TEXT PRIMARY KEY,
  timestamp_ms INTEGER NOT NULL,
  ingested_ms INTEGER,
  trace_id TEXT,
  transaction_id TEXT,
  parent_id TEXT,
  service_name TEXT NOT NULL,
  environment TEXT,
  node_name TEXT,
  service_group TEXT,
  service_module TEXT,
  operation TEXT NOT NULL,
  duration_us INTEGER NOT NULL CHECK(duration_us >= 0),
  sampled INTEGER,
  outcome TEXT,
  http_method TEXT,
  status_code INTEGER,
  account_username TEXT,
  account_namespace TEXT,
  span_kind TEXT NOT NULL,
  event_type TEXT NOT NULL,
  peer_service TEXT,
  peer_address TEXT,
  host_address TEXT,
  url_domain TEXT,
  url_port INTEGER,
  url_path TEXT,
  source_file TEXT,
  source_offset INTEGER,
  created_at_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_time ON events(timestamp_ms);
CREATE INDEX IF NOT EXISTS idx_events_service_time ON events(service_name, timestamp_ms);
CREATE INDEX IF NOT EXISTS idx_events_operation_time ON events(operation, timestamp_ms);
CREATE INDEX IF NOT EXISTS idx_events_account_time ON events(account_username, timestamp_ms);
CREATE INDEX IF NOT EXISTS idx_events_trace ON events(trace_id);
CREATE INDEX IF NOT EXISTS idx_events_parent ON events(trace_id, parent_id);
CREATE INDEX IF NOT EXISTS idx_events_transaction ON events(trace_id, transaction_id);
CREATE INDEX IF NOT EXISTS idx_events_status_time ON events(status_code, timestamp_ms);

CREATE TABLE IF NOT EXISTS services (
  name TEXT PRIMARY KEY, environment TEXT, service_group TEXT, service_module TEXT,
  first_seen_ms INTEGER NOT NULL, last_seen_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
  username TEXT NOT NULL, namespace TEXT NOT NULL DEFAULT '',
  first_seen_ms INTEGER NOT NULL, last_seen_ms INTEGER NOT NULL,
  PRIMARY KEY(username, namespace)
);
CREATE TABLE IF NOT EXISTS latency_rollups (
  bucket_ms INTEGER NOT NULL, bucket_seconds INTEGER NOT NULL DEFAULT 60,
  service_name TEXT NOT NULL, operation TEXT NOT NULL DEFAULT '', account_username TEXT NOT NULL DEFAULT '',
  environment TEXT NOT NULL DEFAULT '', request_count INTEGER NOT NULL,
  server_count INTEGER NOT NULL, http_count INTEGER NOT NULL, duration_sum_us INTEGER NOT NULL,
  histogram_json TEXT NOT NULL, status_2xx INTEGER NOT NULL, status_4xx INTEGER NOT NULL,
  status_5xx INTEGER NOT NULL, denied_count INTEGER NOT NULL, slow_count INTEGER NOT NULL,
  success_count INTEGER NOT NULL, failure_count INTEGER NOT NULL, unknown_count INTEGER NOT NULL,
  sampled_count INTEGER NOT NULL, unsampled_count INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL,
  PRIMARY KEY(bucket_ms, service_name, operation, account_username, environment)
);
CREATE INDEX IF NOT EXISTS idx_rollup_query ON latency_rollups(bucket_ms, environment, service_name);

CREATE TABLE IF NOT EXISTS topology_edges (
  bucket_ms INTEGER NOT NULL, source_service TEXT NOT NULL, target_service TEXT NOT NULL,
  evidence TEXT NOT NULL CHECK(evidence IN ('confirmed','inferred')),
  evidence_detail TEXT NOT NULL, request_count INTEGER NOT NULL, duration_sum_us INTEGER NOT NULL,
  failure_count INTEGER NOT NULL, histogram_json TEXT NOT NULL, updated_at_ms INTEGER NOT NULL,
  PRIMARY KEY(bucket_ms, source_service, target_service, evidence)
);
CREATE INDEX IF NOT EXISTS idx_edges_time ON topology_edges(bucket_ms);

CREATE TABLE IF NOT EXISTS anomalies (
  id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT NOT NULL UNIQUE, entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL, anomaly_type TEXT NOT NULL, first_detected_ms INTEGER NOT NULL,
  last_detected_ms INTEGER NOT NULL, window_start_ms INTEGER NOT NULL, window_end_ms INTEGER NOT NULL,
  current_value REAL NOT NULL, baseline_value REAL, normal_low REAL, normal_high REAL,
  absolute_difference REAL NOT NULL, percent_change REAL, current_samples INTEGER NOT NULL,
  baseline_samples INTEGER NOT NULL, persistence_buckets INTEGER NOT NULL, severity TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open', suppressed_until_ms INTEGER, unit TEXT NOT NULL,
  explanation TEXT NOT NULL, rule TEXT NOT NULL, training_start_ms INTEGER, training_end_ms INTEGER,
  limitations_json TEXT NOT NULL, contributors_json TEXT NOT NULL, trace_ids_json TEXT NOT NULL,
  updated_at_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_anomalies_time ON anomalies(last_detected_ms DESC);
CREATE INDEX IF NOT EXISTS idx_anomalies_status ON anomalies(status, severity);
CREATE TABLE IF NOT EXISTS anomaly_occurrences (
  id INTEGER PRIMARY KEY AUTOINCREMENT, anomaly_id INTEGER NOT NULL REFERENCES anomalies(id),
  start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL, value REAL NOT NULL, created_at_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS checkpoints (
  source TEXT PRIMARY KEY, cursor_json TEXT NOT NULL, updated_at_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  name TEXT PRIMARY KEY, status TEXT NOT NULL, started_at_ms INTEGER, finished_at_ms INTEGER,
  detail TEXT NOT NULL DEFAULT '', processed_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY, applied_at_ms INTEGER NOT NULL
);

