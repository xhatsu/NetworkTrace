-- Keep measured bandwidth beside transaction counts and latency in worker-owned
-- 1-minute and 5-minute metric buckets.
ALTER TABLE metric_buckets ADD COLUMN IF NOT EXISTS request_bytes UInt64 DEFAULT 0;
ALTER TABLE metric_buckets ADD COLUMN IF NOT EXISTS response_bytes UInt64 DEFAULT 0;
ALTER TABLE metric_buckets ADD COLUMN IF NOT EXISTS request_bytes_samples UInt64 DEFAULT 0;
ALTER TABLE metric_buckets ADD COLUMN IF NOT EXISTS response_bytes_samples UInt64 DEFAULT 0;
