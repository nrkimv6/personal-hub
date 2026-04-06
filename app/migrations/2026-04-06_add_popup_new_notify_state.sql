-- Ensure popup_new state exists in notification_settings.notify_states
CREATE TABLE IF NOT EXISTS notification_settings (
    id INTEGER PRIMARY KEY,
    enable_telegram INTEGER DEFAULT 1,
    enable_desktop INTEGER DEFAULT 1,
    notify_states TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO notification_settings (id, enable_telegram, enable_desktop, notify_states)
VALUES (1, 1, 1, '["available", "booking_success", "booking_failed", "error", "startup", "shutdown"]');

UPDATE notification_settings
SET notify_states = CASE
    WHEN notify_states IS NULL OR TRIM(notify_states) = '' THEN '["popup_new"]'
    WHEN notify_states LIKE '%"popup_new"%' THEN notify_states
    WHEN TRIM(notify_states) = '[]' THEN '["popup_new"]'
    WHEN SUBSTR(TRIM(notify_states), -1, 1) = ']' THEN
        SUBSTR(TRIM(notify_states), 1, LENGTH(TRIM(notify_states)) - 1) || ',"popup_new"]'
    ELSE notify_states
END
WHERE id = 1;
