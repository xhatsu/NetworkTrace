CREATE TABLE IF NOT EXISTS principals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  principal_name TEXT NOT NULL UNIQUE,
  principal_type TEXT NOT NULL DEFAULT 'unknown',
  first_seen INTEGER NOT NULL,
  last_seen INTEGER NOT NULL,
  total_requests INTEGER NOT NULL DEFAULT 0,
  unique_callers INTEGER NOT NULL DEFAULT 0,
  unique_sources INTEGER NOT NULL DEFAULT 0,
  unique_targets INTEGER NOT NULL DEFAULT 0,
  unique_operations INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_principals_last_seen ON principals(last_seen DESC);

CREATE TABLE IF NOT EXISTS principal_callers (
  principal_name TEXT NOT NULL,
  caller_service TEXT NOT NULL,
  first_seen INTEGER NOT NULL,
  last_seen INTEGER NOT NULL,
  observation_count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(principal_name, caller_service)
);
CREATE TABLE IF NOT EXISTS principal_sources (
  principal_name TEXT NOT NULL,
  source_ip TEXT NOT NULL,
  first_seen INTEGER NOT NULL,
  last_seen INTEGER NOT NULL,
  observation_count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(principal_name, source_ip)
);
CREATE TABLE IF NOT EXISTS principal_targets (
  principal_name TEXT NOT NULL,
  target_service TEXT NOT NULL,
  first_seen INTEGER NOT NULL,
  last_seen INTEGER NOT NULL,
  observation_count INTEGER NOT NULL DEFAULT 0,
  error_count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(principal_name, target_service)
);
CREATE TABLE IF NOT EXISTS principal_operations (
  principal_name TEXT NOT NULL,
  target_service TEXT NOT NULL,
  operation TEXT NOT NULL,
  first_seen INTEGER NOT NULL,
  last_seen INTEGER NOT NULL,
  observation_count INTEGER NOT NULL DEFAULT 0,
  error_count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(principal_name, target_service, operation)
);

CREATE TABLE IF NOT EXISTS principal_relationships (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  principal_name TEXT NOT NULL,
  caller_service TEXT NOT NULL DEFAULT '',
  caller_instance TEXT NOT NULL DEFAULT '',
  source_ip TEXT NOT NULL DEFAULT '',
  target_service TEXT NOT NULL,
  target_instance TEXT NOT NULL DEFAULT '',
  target_ip TEXT NOT NULL DEFAULT '',
  target_port INTEGER NOT NULL DEFAULT 0,
  operation TEXT NOT NULL,
  http_method TEXT NOT NULL DEFAULT '',
  first_seen INTEGER NOT NULL,
  last_seen INTEGER NOT NULL,
  observation_count INTEGER NOT NULL DEFAULT 0,
  success_count INTEGER NOT NULL DEFAULT 0,
  error_count INTEGER NOT NULL DEFAULT 0,
  UNIQUE(principal_name,caller_service,caller_instance,source_ip,target_service,target_instance,target_ip,target_port,operation,http_method)
);
CREATE INDEX IF NOT EXISTS idx_principal_rel_name ON principal_relationships(principal_name);
CREATE INDEX IF NOT EXISTS idx_principal_rel_caller ON principal_relationships(principal_name,caller_service);
CREATE INDEX IF NOT EXISTS idx_principal_rel_target ON principal_relationships(principal_name,target_service);
CREATE INDEX IF NOT EXISTS idx_principal_rel_operation ON principal_relationships(principal_name,operation);
CREATE INDEX IF NOT EXISTS idx_principal_rel_source ON principal_relationships(principal_name,source_ip);
CREATE INDEX IF NOT EXISTS idx_principal_rel_last_seen ON principal_relationships(last_seen DESC);

CREATE TABLE IF NOT EXISTS principal_hourly_activity (
  principal_name TEXT NOT NULL,
  day_of_week INTEGER NOT NULL,
  hour_of_day INTEGER NOT NULL,
  observation_count INTEGER NOT NULL DEFAULT 0,
  error_count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(principal_name,day_of_week,hour_of_day)
);
CREATE TABLE IF NOT EXISTS principal_daily_stats (
  principal_name TEXT NOT NULL,
  day_start INTEGER NOT NULL,
  observation_count INTEGER NOT NULL DEFAULT 0,
  error_count INTEGER NOT NULL DEFAULT 0,
  unique_callers INTEGER NOT NULL DEFAULT 0,
  unique_sources INTEGER NOT NULL DEFAULT 0,
  unique_targets INTEGER NOT NULL DEFAULT 0,
  unique_operations INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(principal_name,day_start)
);
CREATE TABLE IF NOT EXISTS principal_baselines (
  principal_name TEXT NOT NULL,
  dimension_type TEXT NOT NULL,
  dimension_value TEXT NOT NULL,
  first_seen INTEGER NOT NULL,
  last_seen INTEGER NOT NULL,
  observation_count INTEGER NOT NULL DEFAULT 0,
  distribution_share REAL NOT NULL DEFAULT 0,
  PRIMARY KEY(principal_name,dimension_type,dimension_value)
);
CREATE INDEX IF NOT EXISTS idx_principal_baseline_lookup ON principal_baselines(principal_name,dimension_type);

CREATE TABLE IF NOT EXISTS principal_change_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fingerprint TEXT NOT NULL UNIQUE,
  principal_name TEXT NOT NULL,
  change_type TEXT NOT NULL,
  severity TEXT NOT NULL,
  score INTEGER NOT NULL,
  detected_at INTEGER NOT NULL,
  caller_service TEXT,
  source_ip TEXT,
  target_service TEXT,
  operation TEXT,
  old_value TEXT,
  new_value TEXT,
  first_observed INTEGER NOT NULL,
  reason_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new','reviewed','expected','ignored')),
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_principal_changes_time ON principal_change_events(detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_principal_changes_name ON principal_change_events(principal_name,detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_principal_changes_filter ON principal_change_events(change_type,severity,status,detected_at DESC);
