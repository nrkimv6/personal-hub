-- 006_add_notification_settings.sql
-- 알림 설정 테이블 추가
-- 날짜: 2025-12-03

-- notification_settings 테이블 생성
CREATE TABLE IF NOT EXISTS notification_settings (
    id INTEGER PRIMARY KEY,
    enable_telegram INTEGER DEFAULT 1,
    enable_desktop INTEGER DEFAULT 1,
    notify_states TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 초기 데이터 삽입 (없으면)
INSERT OR IGNORE INTO notification_settings (id, enable_telegram, enable_desktop, notify_states)
VALUES (1, 1, 1, '["available", "booking_success", "booking_failed", "error", "popup_new"]');
