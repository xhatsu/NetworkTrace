CREATE TABLE IF NOT EXISTS address_mappings (
  address TEXT NOT NULL,
  service_name TEXT NOT NULL,
  valid_from_ms INTEGER NOT NULL,
  valid_to_ms INTEGER,
  source TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 1.0 CHECK(confidence >= 0 AND confidence <= 1),
  PRIMARY KEY(address, service_name, valid_from_ms)
);
CREATE INDEX IF NOT EXISTS idx_address_mapping_lookup ON address_mappings(address, valid_from_ms, valid_to_ms);

CREATE TABLE IF NOT EXISTS dirty_buckets (
  bucket_ms INTEGER PRIMARY KEY,
  reason TEXT NOT NULL,
  created_at_ms INTEGER NOT NULL
);
