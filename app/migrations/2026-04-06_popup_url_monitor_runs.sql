-- Popup URL monitor run history table
CREATE TABLE IF NOT EXISTS popup_url_monitor_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    monitor_id INTEGER NOT NULL REFERENCES popup_url_monitors(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'success',
    new_count INTEGER NOT NULL DEFAULT 0,
    has_new INTEGER NOT NULL DEFAULT 0,
    proxy_url TEXT,
    request_profile TEXT,
    fallback_applied INTEGER NOT NULL DEFAULT 0,
    snapshot_json TEXT,
    error_message TEXT,
    started_at TEXT DEFAULT (datetime('now', 'localtime')),
    finished_at TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_popup_url_monitor_runs_monitor_id
    ON popup_url_monitor_runs(monitor_id);

CREATE INDEX IF NOT EXISTS idx_popup_url_monitor_runs_created_at
    ON popup_url_monitor_runs(created_at);

CREATE INDEX IF NOT EXISTS idx_popup_url_monitor_runs_has_new
    ON popup_url_monitor_runs(has_new);
