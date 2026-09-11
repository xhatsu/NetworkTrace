-- Migration 011: Canonical request observations, bounded incidents, and multi-layer baselines

-- Add canonical observation columns to traces
ALTER TABLE traces ADD COLUMN environment TEXT DEFAULT 'production';
ALTER TABLE traces ADD COLUMN principal_id TEXT;
ALTER TABLE traces ADD COLUMN identity_source TEXT DEFAULT 'unknown';
ALTER TABLE traces ADD COLUMN auth_result TEXT DEFAULT 'unknown';
ALTER TABLE traces ADD COLUMN auth_evidence TEXT DEFAULT 'unknown';
ALTER TABLE traces ADD COLUMN caller_resolution_method TEXT DEFAULT 'none';
ALTER TABLE traces ADD COLUMN caller_confidence REAL DEFAULT 0.0;
ALTER TABLE traces ADD COLUMN network_peer_ip TEXT;
ALTER TABLE traces ADD COLUMN original_client_ip TEXT;
ALTER TABLE traces ADD COLUMN original_client_ip_trusted INTEGER DEFAULT 0;
ALTER TABLE traces ADD COLUMN source_group TEXT;
ALTER TABLE traces ADD COLUMN operation_key TEXT;
ALTER TABLE traces ADD COLUMN soap_fault_code TEXT;
ALTER TABLE traces ADD COLUMN outcome_class TEXT DEFAULT 'unknown';
ALTER TABLE traces ADD COLUMN sampling_context TEXT;
ALTER TABLE traces ADD COLUMN dedup_key TEXT;

CREATE INDEX IF NOT EXISTS idx_traces_dedup_key ON traces(dedup_key);
CREATE INDEX IF NOT EXISTS idx_traces_principal_id_ts ON traces(principal_id, timestamp_ms);
CREATE INDEX IF NOT EXISTS idx_traces_env_ts ON traces(environment, timestamp_ms);
CREATE INDEX IF NOT EXISTS idx_traces_op_key ON traces(operation_key, timestamp_ms);

-- Add incident, importance, and classification columns to principal_change_events
ALTER TABLE principal_change_events ADD COLUMN incident_id TEXT;
ALTER TABLE principal_change_events ADD COLUMN principal_id TEXT;
ALTER TABLE principal_change_events ADD COLUMN environment TEXT DEFAULT 'production';
ALTER TABLE principal_change_events ADD COLUMN base_importance TEXT;
ALTER TABLE principal_change_events ADD COLUMN category TEXT DEFAULT 'behavioral';
ALTER TABLE principal_change_events ADD COLUMN family TEXT;
ALTER TABLE principal_change_events ADD COLUMN reliability TEXT;
ALTER TABLE principal_change_events ADD COLUMN review_reason TEXT;
ALTER TABLE principal_change_events ADD COLUMN reviewed_by TEXT;
ALTER TABLE principal_change_events ADD COLUMN expires_at INTEGER;

CREATE INDEX IF NOT EXISTS idx_pce_incident_id ON principal_change_events(incident_id);
CREATE INDEX IF NOT EXISTS idx_pce_principal_id ON principal_change_events(principal_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_pce_family ON principal_change_events(family, detected_at DESC);

-- Bounded Incident Object
CREATE TABLE IF NOT EXISTS incidents (
  incident_id TEXT PRIMARY KEY,
  principal_id TEXT NOT NULL,
  environment TEXT NOT NULL DEFAULT 'production',
  category TEXT NOT NULL CHECK(category IN ('behavioral', 'authentication', 'operational', 'data_quality', 'audit')),
  scope TEXT NOT NULL,
  started_at INTEGER NOT NULL,
  last_seen_at INTEGER NOT NULL,
  closed_at INTEGER,
  status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'investigating', 'resolved', 'suppressed', 'accepted')),
  score INTEGER NOT NULL DEFAULT 0,
  priority TEXT NOT NULL DEFAULT 'low' CHECK(priority IN ('low', 'medium', 'high')),
  confidence REAL NOT NULL DEFAULT 1.0,
  family_scores_json TEXT NOT NULL DEFAULT '{}',
  contributing_event_ids_json TEXT NOT NULL DEFAULT '[]',
  suppressed_contributions_json TEXT NOT NULL DEFAULT '[]',
  successor_id TEXT,
  review_notes TEXT,
  reviewed_by TEXT,
  reviewed_at INTEGER,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_incidents_principal ON incidents(principal_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_incidents_priority ON incidents(priority, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_incidents_category ON incidents(category, started_at DESC);

-- Layer 1: Historical registry (First seen, last seen, observation count for dimensions and relationships)
CREATE TABLE IF NOT EXISTS historical_registry (
  registry_key TEXT PRIMARY KEY,
  principal_id TEXT NOT NULL,
  dimension_type TEXT NOT NULL,
  dimension_value TEXT NOT NULL,
  first_seen INTEGER NOT NULL,
  last_seen INTEGER NOT NULL,
  observation_count INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hist_reg_principal ON historical_registry(principal_id, dimension_type);

-- Layer 2: Established baseline (Accepted behavior used to evaluate new observations)
CREATE TABLE IF NOT EXISTS established_baselines (
  baseline_key TEXT PRIMARY KEY,
  principal_id TEXT NOT NULL,
  dimension_type TEXT NOT NULL,
  dimension_value TEXT NOT NULL,
  first_seen INTEGER NOT NULL,
  last_seen INTEGER NOT NULL,
  observation_count INTEGER NOT NULL DEFAULT 0,
  distribution_share REAL NOT NULL DEFAULT 0.0,
  promoted_at INTEGER NOT NULL,
  promotion_reason TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_estab_base_principal ON established_baselines(principal_id, dimension_type);

-- Layer 3: Candidate behavior (Newly observed behavior awaiting repeated support or review)
CREATE TABLE IF NOT EXISTS candidate_behaviors (
  candidate_key TEXT PRIMARY KEY,
  principal_id TEXT NOT NULL,
  dimension_type TEXT NOT NULL,
  dimension_value TEXT NOT NULL,
  first_seen INTEGER NOT NULL,
  last_seen INTEGER NOT NULL,
  distinct_days_count INTEGER NOT NULL DEFAULT 1,
  distinct_windows_count INTEGER NOT NULL DEFAULT 1,
  observation_count INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'promoted', 'blocked', 'rejected')),
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cand_behav_principal ON candidate_behaviors(principal_id, status);

-- Operator Overrides (Explicit accepted changes by humans)
CREATE TABLE IF NOT EXISTS operator_overrides (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scope_type TEXT NOT NULL,
  scope_value TEXT NOT NULL,
  reason TEXT NOT NULL,
  operator TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  expires_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_op_overrides_scope ON operator_overrides(scope_type, scope_value);

-- Telemetry Quality Tracking
CREATE TABLE IF NOT EXISTS telemetry_quality_windows (
  window_start_sec INTEGER PRIMARY KEY,
  window_end_sec INTEGER NOT NULL,
  total_spans INTEGER NOT NULL DEFAULT 0,
  counted_requests INTEGER NOT NULL DEFAULT 0,
  caller_linked_count INTEGER NOT NULL DEFAULT 0,
  caller_linkage_rate REAL NOT NULL DEFAULT 0.0,
  username_extracted_count INTEGER NOT NULL DEFAULT 0,
  username_extraction_rate REAL NOT NULL DEFAULT 0.0,
  is_collection_gap INTEGER NOT NULL DEFAULT 0,
  sampling_ratio REAL NOT NULL DEFAULT 1.0,
  created_at INTEGER NOT NULL
);
