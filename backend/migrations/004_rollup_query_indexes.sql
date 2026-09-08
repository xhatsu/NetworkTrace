CREATE INDEX IF NOT EXISTS idx_rollup_level_time ON latency_rollups(operation,account_username,bucket_ms,environment,service_name);
CREATE INDEX IF NOT EXISTS idx_rollup_account_time ON latency_rollups(account_username,bucket_ms);
