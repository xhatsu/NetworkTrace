CREATE TABLE IF NOT EXISTS traces (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_uid TEXT UNIQUE,
  timestamp INTEGER NOT NULL,
  timestamp_ms INTEGER NOT NULL,

  trace_id TEXT NOT NULL,
  span_id TEXT NOT NULL,
  parent_span_id TEXT,

  service_name TEXT NOT NULL,
  service_instance TEXT,
  service_environment TEXT DEFAULT 'production',

  caller_service TEXT,
  caller_instance TEXT,
  caller_ip TEXT,

  target_service TEXT NOT NULL,
  target_instance TEXT,
  target_ip TEXT,
  target_port INTEGER,

  principal_name TEXT NOT NULL DEFAULT 'unknown',

  operation TEXT NOT NULL,
  http_method TEXT,
  http_route TEXT,

  http_status INTEGER,
  status_class TEXT,

  duration_ms REAL NOT NULL CHECK(duration_ms >= 0),
  duration_us INTEGER NOT NULL CHECK(duration_us >= 0),
  outcome TEXT,

  protocol TEXT DEFAULT 'http',
  span_kind TEXT DEFAULT 'server',

  attributes_json TEXT,
  created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_traces_ts ON traces(timestamp_ms);
CREATE INDEX IF NOT EXISTS idx_traces_trace_id ON traces(trace_id);
CREATE INDEX IF NOT EXISTS idx_traces_svc_ts ON traces(service_name, timestamp_ms);
CREATE INDEX IF NOT EXISTS idx_traces_caller_ts ON traces(caller_service, timestamp_ms);
CREATE INDEX IF NOT EXISTS idx_traces_target_ts ON traces(target_service, timestamp_ms);
CREATE INDEX IF NOT EXISTS idx_traces_principal_ts ON traces(principal_name, timestamp_ms);
CREATE INDEX IF NOT EXISTS idx_traces_op_ts ON traces(operation, timestamp_ms);
CREATE INDEX IF NOT EXISTS idx_traces_caller_target ON traces(caller_service, target_service, timestamp_ms);
CREATE INDEX IF NOT EXISTS idx_traces_target_op ON traces(target_service, operation, timestamp_ms);
CREATE INDEX IF NOT EXISTS idx_traces_principal_target ON traces(principal_name, target_service, timestamp_ms);

CREATE TABLE IF NOT EXISTS metric_buckets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bucket_start INTEGER NOT NULL,
  bucket_size INTEGER NOT NULL,

  caller_service TEXT NOT NULL DEFAULT '',
  target_service TEXT NOT NULL DEFAULT '',
  principal_name TEXT NOT NULL DEFAULT '',
  operation TEXT NOT NULL DEFAULT '',

  request_count INTEGER NOT NULL DEFAULT 0,
  error_count INTEGER NOT NULL DEFAULT 0,

  latency_sum REAL NOT NULL DEFAULT 0.0,
  latency_avg REAL NOT NULL DEFAULT 0.0,
  latency_min REAL NOT NULL DEFAULT 0.0,
  latency_max REAL NOT NULL DEFAULT 0.0,

  latency_p50 REAL NOT NULL DEFAULT 0.0,
  latency_p95 REAL NOT NULL DEFAULT 0.0,
  latency_p99 REAL NOT NULL DEFAULT 0.0,

  created_at INTEGER NOT NULL,
  UNIQUE(bucket_start, bucket_size, caller_service, target_service, principal_name, operation)
);

CREATE INDEX IF NOT EXISTS idx_mb_start_size ON metric_buckets(bucket_start, bucket_size);
CREATE INDEX IF NOT EXISTS idx_mb_target ON metric_buckets(target_service, bucket_size, bucket_start);
CREATE INDEX IF NOT EXISTS idx_mb_principal ON metric_buckets(principal_name, bucket_size, bucket_start);
CREATE INDEX IF NOT EXISTS idx_mb_edge ON metric_buckets(caller_service, target_service, bucket_size, bucket_start);

CREATE TABLE IF NOT EXISTS service_edges (
  caller_service TEXT NOT NULL,
  target_service TEXT NOT NULL,

  first_seen INTEGER NOT NULL,
  last_seen INTEGER NOT NULL,

  request_count INTEGER NOT NULL DEFAULT 0,
  error_count INTEGER NOT NULL DEFAULT 0,
  error_rate REAL NOT NULL DEFAULT 0.0,

  avg_latency REAL NOT NULL DEFAULT 0.0,
  p95_latency REAL NOT NULL DEFAULT 0.0,

  principal_count INTEGER NOT NULL DEFAULT 0,
  operation_count INTEGER NOT NULL DEFAULT 0,

  PRIMARY KEY(caller_service, target_service)
);

CREATE TABLE IF NOT EXISTS principal_service_edges (
  principal_name TEXT NOT NULL,
  caller_service TEXT NOT NULL,
  target_service TEXT NOT NULL,

  first_seen INTEGER NOT NULL,
  last_seen INTEGER NOT NULL,

  request_count INTEGER NOT NULL DEFAULT 0,
  error_rate REAL NOT NULL DEFAULT 0.0,
  p95_latency REAL NOT NULL DEFAULT 0.0,

  PRIMARY KEY(principal_name, caller_service, target_service)
);

CREATE TABLE IF NOT EXISTS baseline_metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dimension_type TEXT NOT NULL,
  dimension_key TEXT NOT NULL,

  hour_of_day INTEGER NOT NULL,
  day_of_week INTEGER NOT NULL,

  sample_count INTEGER NOT NULL DEFAULT 0,

  rps_median REAL NOT NULL DEFAULT 0.0,
  rps_mad REAL NOT NULL DEFAULT 0.0,

  latency_p50_median REAL NOT NULL DEFAULT 0.0,
  latency_p95_median REAL NOT NULL DEFAULT 0.0,
  latency_p95_mad REAL NOT NULL DEFAULT 0.0,

  error_rate_median REAL NOT NULL DEFAULT 0.0,
  error_rate_mad REAL NOT NULL DEFAULT 0.0,

  updated_at INTEGER NOT NULL,
  UNIQUE(dimension_type, dimension_key, hour_of_day, day_of_week)
);

CREATE TABLE IF NOT EXISTS anomaly_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  detected_at INTEGER NOT NULL,

  anomaly_type TEXT NOT NULL,

  severity TEXT NOT NULL,
  score INTEGER NOT NULL,
  confidence REAL NOT NULL DEFAULT 1.0,

  caller_service TEXT,
  target_service TEXT,
  principal_name TEXT,
  operation TEXT,
  instance TEXT,

  baseline_value REAL,
  current_value REAL,
  delta_percentage REAL,

  first_seen INTEGER,
  last_seen INTEGER,

  status TEXT NOT NULL DEFAULT 'open',
  acknowledged INTEGER NOT NULL DEFAULT 0,

  reason_json TEXT NOT NULL,
  metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_ae_detected ON anomaly_events(detected_at);
CREATE INDEX IF NOT EXISTS idx_ae_target ON anomaly_events(target_service, detected_at);
CREATE INDEX IF NOT EXISTS idx_ae_principal ON anomaly_events(principal_name, detected_at);
CREATE INDEX IF NOT EXISTS idx_ae_status ON anomaly_events(status, severity);
