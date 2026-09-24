-- Preserve exact authentication failure counts in bounded topology read models.
-- Interactive APIs can distinguish 401/403 activity without reading raw spans.
ALTER TABLE topology_service_edges_5m ADD COLUMN IF NOT EXISTS auth_failure_count UInt64 DEFAULT 0 AFTER error_count;
ALTER TABLE topology_api_edges_5m ADD COLUMN IF NOT EXISTS auth_failure_count UInt64 DEFAULT 0 AFTER error_count;
ALTER TABLE topology_principal_edges_5m ADD COLUMN IF NOT EXISTS auth_failure_count UInt64 DEFAULT 0 AFTER error_count;
ALTER TABLE topology_principal_ip_5m ADD COLUMN IF NOT EXISTS auth_failure_count UInt64 DEFAULT 0 AFTER error_count;
ALTER TABLE topology_service_current ADD COLUMN IF NOT EXISTS auth_failure_count UInt64 DEFAULT 0 AFTER error_count;
ALTER TABLE topology_api_current ADD COLUMN IF NOT EXISTS auth_failure_count UInt64 DEFAULT 0 AFTER error_count;
ALTER TABLE topology_principal_current ADD COLUMN IF NOT EXISTS auth_failure_count UInt64 DEFAULT 0 AFTER error_count;
ALTER TABLE topology_principal_ip_current ADD COLUMN IF NOT EXISTS auth_failure_count UInt64 DEFAULT 0 AFTER error_count;
