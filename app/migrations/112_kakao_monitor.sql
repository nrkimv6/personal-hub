-- 112_kakao_monitor.sql
-- 카카오톡 채팅방 모니터링 테이블 생성

-- 감시 설정 (채팅방 단위)
CREATE TABLE IF NOT EXISTS kakao_watch_configs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_name           TEXT    NOT NULL,
    polling_interval_sec INTEGER NOT NULL DEFAULT 3,
    is_active           INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT    DEFAULT (datetime('now', 'localtime')),
    updated_at          TEXT    DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_kakao_watch_configs_chat_name
    ON kakao_watch_configs(chat_name);

CREATE INDEX IF NOT EXISTS idx_kakao_watch_configs_is_active
    ON kakao_watch_configs(is_active);

-- 키워드 목록
-- action_type: 'collect' (게시물 수집) | 'alert_only' (알림만)
CREATE TABLE IF NOT EXISTS kakao_keywords (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    config_id   INTEGER NOT NULL REFERENCES kakao_watch_configs(id) ON DELETE CASCADE,
    keyword     TEXT    NOT NULL,
    action_type TEXT    NOT NULL DEFAULT 'collect',
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_kakao_keywords_config_id
    ON kakao_keywords(config_id);

-- 수집된 게시물 이력
-- status: 'success' | 'partial' | 'failed'
CREATE TABLE IF NOT EXISTS kakao_collected_posts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    config_id         INTEGER NOT NULL REFERENCES kakao_watch_configs(id) ON DELETE CASCADE,
    keyword_id        INTEGER REFERENCES kakao_keywords(id) ON DELETE SET NULL,
    matched_keyword   TEXT,
    trigger_message   TEXT,
    collected_content TEXT,
    collected_at      TEXT    DEFAULT (datetime('now', 'localtime')),
    screenshot_path   TEXT,
    status            TEXT    NOT NULL DEFAULT 'success'
);

CREATE INDEX IF NOT EXISTS idx_kakao_collected_posts_config_id
    ON kakao_collected_posts(config_id);

CREATE INDEX IF NOT EXISTS idx_kakao_collected_posts_status
    ON kakao_collected_posts(status);

CREATE INDEX IF NOT EXISTS idx_kakao_collected_posts_collected_at
    ON kakao_collected_posts(collected_at);

-- 알림 발송 이력
CREATE TABLE IF NOT EXISTS kakao_alert_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id    INTEGER NOT NULL REFERENCES kakao_collected_posts(id) ON DELETE CASCADE,
    alert_type TEXT    NOT NULL,
    sent_at    TEXT    DEFAULT (datetime('now', 'localtime')),
    result     TEXT
);

CREATE INDEX IF NOT EXISTS idx_kakao_alert_logs_post_id
    ON kakao_alert_logs(post_id);
