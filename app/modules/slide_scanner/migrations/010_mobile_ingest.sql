CREATE TABLE IF NOT EXISTS mobile_ingest_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    device_serial TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    source_uri TEXT NOT NULL,
    source_mtime_utc TEXT,
    source_size_bytes INTEGER,
    source_sha256 TEXT,
    pc_inbox_path TEXT NOT NULL,
    captured_at_utc TEXT NOT NULL,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    approval_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (approval_status IN ('PENDING', 'APPROVED', 'REJECTED')),
    remote_delete_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (remote_delete_status IN ('PENDING', 'DONE', 'FAILED')),
    handoff_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (handoff_status IN ('PENDING', 'DONE', 'FAILED')),
    local_cleanup_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (local_cleanup_status IN ('PENDING', 'DONE', 'FAILED')),
    slide_id INTEGER,
    error_message TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (slide_id) REFERENCES slides(id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_mobile_ingest_dedupe
ON mobile_ingest_items(device_serial, source_uri, source_mtime_utc, source_size_bytes);

CREATE INDEX IF NOT EXISTS idx_mobile_ingest_approval_captured
ON mobile_ingest_items(approval_status, captured_at_utc DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_mobile_ingest_remote_delete
ON mobile_ingest_items(remote_delete_status);

CREATE INDEX IF NOT EXISTS idx_mobile_ingest_handoff
ON mobile_ingest_items(handoff_status);

CREATE INDEX IF NOT EXISTS idx_mobile_ingest_local_cleanup
ON mobile_ingest_items(local_cleanup_status);
