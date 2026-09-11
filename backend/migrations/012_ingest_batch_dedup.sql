-- Migration 012: Ingestion batch deduplication table for reliable shipper retries
CREATE TABLE IF NOT EXISTS ingest_batches (
    batch_id TEXT PRIMARY KEY,
    node TEXT,
    record_count INTEGER NOT NULL DEFAULT 0,
    received_at_ms INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'accepted'
);

CREATE INDEX IF NOT EXISTS idx_ingest_batches_received_at ON ingest_batches(received_at_ms);
CREATE INDEX IF NOT EXISTS idx_ingest_batches_node ON ingest_batches(node);
