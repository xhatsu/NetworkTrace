-- Migration 009: Oldkernel Agent Statistics Protocol v1
-- Stores agent health/resource telemetry separately from captured trace events.
-- Two tables:
--   agent_stats_latest  - one live row per (node, instance_id) for dashboards
--   agent_stats_history - append-only time-series for trend analysis

CREATE TABLE IF NOT EXISTS agent_stats_latest (
    node            TEXT    NOT NULL,
    instance_id     TEXT    NOT NULL,
    sequence        INTEGER NOT NULL,
    observed_at     INTEGER NOT NULL,   -- Unix seconds
    window_seconds  INTEGER NOT NULL,
    mode            TEXT,
    status          TEXT    NOT NULL,
    reasons_json    TEXT    NOT NULL DEFAULT '[]',

    -- capture sub-object (flattened)
    cap_packets_total           INTEGER,
    cap_packets_delta           INTEGER,
    cap_packet_bytes_total      INTEGER,
    cap_packet_bytes_delta      INTEGER,
    cap_kernel_drops_total      INTEGER,
    cap_kernel_drops_delta      INTEGER,
    cap_kernel_drop_percent     REAL,
    cap_invalid_frames_total    INTEGER,
    cap_events_emitted_total    INTEGER,
    cap_events_emitted_delta    INTEGER,
    cap_flows_active            INTEGER,
    cap_pending_requests        INTEGER,
    cap_wsse_body_flows_active  INTEGER,

    -- shipping sub-object (flattened)
    ship_events_in_total            INTEGER,
    ship_events_in_delta            INTEGER,
    ship_events_pushed_total        INTEGER,
    ship_events_pushed_delta        INTEGER,
    ship_events_dropped_total       INTEGER,
    ship_events_dropped_delta       INTEGER,
    ship_drop_causes_json           TEXT,
    ship_batches_pushed_total       INTEGER,
    ship_batches_pushed_delta       INTEGER,
    ship_batches_failed_total       INTEGER,
    ship_batches_failed_delta       INTEGER,
    ship_bytes_pushed_total         INTEGER,
    ship_bytes_pushed_delta         INTEGER,
    ship_push_events_per_second     REAL,
    ship_push_kbps                  REAL,
    ship_drop_events_per_second     REAL,
    ship_drop_percent               REAL,
    ship_queue_depth_events         INTEGER,
    ship_queue_capacity_events      INTEGER,
    ship_queue_high_water_events    INTEGER,
    ship_last_push_http_status      INTEGER,
    ship_last_success_at            INTEGER,
    ship_consecutive_failures       INTEGER,
    ship_stats_samples_dropped_total INTEGER,

    -- resources sub-object (flattened)
    res_cpu_user_seconds        REAL,
    res_cpu_system_seconds      REAL,
    res_cpu_percent_one_core    REAL,
    res_rss_bytes               INTEGER,
    res_virtual_bytes           INTEGER,
    res_open_fds                INTEGER,
    res_threads                 INTEGER,

    -- limits sub-object (flattened)
    lim_cpu_core                INTEGER,
    lim_address_space_bytes     INTEGER,
    lim_ship_rate_kbps          INTEGER,
    lim_http_body_max_bytes     INTEGER,
    lim_ship_threads_max        INTEGER,
    lim_wsse_body_bytes         INTEGER,

    raw_json    TEXT    NOT NULL,       -- full document for forensic reference
    ingested_at INTEGER NOT NULL,       -- server Unix ms

    PRIMARY KEY (node, instance_id)
);

CREATE TABLE IF NOT EXISTS agent_stats_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    node        TEXT    NOT NULL,
    instance_id TEXT    NOT NULL,
    sequence    INTEGER NOT NULL,
    observed_at INTEGER NOT NULL,
    window_seconds INTEGER NOT NULL,
    mode        TEXT,
    status      TEXT    NOT NULL,
    reasons_json TEXT   NOT NULL DEFAULT '[]',
    raw_json    TEXT    NOT NULL,
    ingested_at INTEGER NOT NULL,

    UNIQUE (node, instance_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_agent_stats_history_node_time
    ON agent_stats_history(node, observed_at);
CREATE INDEX IF NOT EXISTS idx_agent_stats_latest_status
    ON agent_stats_latest(status, observed_at);
