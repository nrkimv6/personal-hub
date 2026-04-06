-- Popup URL monitor base table
CREATE TABLE IF NOT EXISTS popup_url_monitors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    url TEXT NOT NULL,
    request_profile TEXT NOT NULL DEFAULT 'A',
    fallback_strategy TEXT NOT NULL DEFAULT 'reinforce',
    proxy_enabled INTEGER NOT NULL DEFAULT 0,
    notify_on_new INTEGER NOT NULL DEFAULT 1,
    min_new_count INTEGER NOT NULL DEFAULT 1,
    monitoring_mode TEXT NOT NULL DEFAULT 'anonymous',
    service_account_id INTEGER REFERENCES service_accounts(id) ON DELETE SET NULL,
    browser_fallback_enabled INTEGER NOT NULL DEFAULT 0,
    is_enabled INTEGER NOT NULL DEFAULT 1,
    latest_snapshot_json TEXT,
    latest_snapshot_hash TEXT,
    latest_checked_at TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_popup_url_monitors_is_enabled
    ON popup_url_monitors(is_enabled);

CREATE INDEX IF NOT EXISTS idx_popup_url_monitors_monitoring_mode
    ON popup_url_monitors(monitoring_mode);

CREATE INDEX IF NOT EXISTS idx_popup_url_monitors_request_profile
    ON popup_url_monitors(request_profile);
