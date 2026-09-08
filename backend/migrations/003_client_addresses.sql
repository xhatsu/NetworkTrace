ALTER TABLE events ADD COLUMN client_ip TEXT;
ALTER TABLE events ADD COLUMN source_ip TEXT;
CREATE INDEX IF NOT EXISTS idx_events_client_ip_time ON events(client_ip,timestamp_ms);
CREATE INDEX IF NOT EXISTS idx_events_source_ip_time ON events(source_ip,timestamp_ms);
