ALTER TABLE popup_url_monitors
ADD COLUMN IF NOT EXISTS monitor_kind VARCHAR(32) NOT NULL DEFAULT 'popup_list';

ALTER TABLE popup_url_monitors
ADD COLUMN IF NOT EXISTS stop_on_detected BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE popup_url_monitors
ADD COLUMN IF NOT EXISTS detected_at TIMESTAMP NULL;

UPDATE popup_url_monitors
SET monitor_kind = 'popup_list'
WHERE monitor_kind IS NULL OR monitor_kind = '';

