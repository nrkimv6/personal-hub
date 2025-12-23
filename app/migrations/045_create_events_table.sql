-- 독립 이벤트 테이블 생성
-- Instagram과 분리된 이벤트 관리를 위한 테이블

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 기본 정보
    title TEXT NOT NULL,
    event_type TEXT NOT NULL DEFAULT 'event',  -- event/popup/ambassador/other
    status TEXT DEFAULT 'active',               -- active/ended/cancelled

    -- 참여 URL (핵심)
    event_url TEXT,
    url_type TEXT,                              -- google_form/naver_form/shop/survey/other
    additional_urls JSON DEFAULT '[]',

    -- 기간
    event_start DATE,
    event_end DATE,
    announcement_date DATE,

    -- 이벤트 상세
    organizer TEXT,
    summary TEXT,
    prizes JSON DEFAULT '[]',
    winner_count INTEGER,
    purchase_required TEXT,                     -- yes_all/yes_partial/no

    -- 팝업 전용 (event_type='popup')
    location_venue TEXT,
    location_address TEXT,

    -- 출처 정보
    source_type TEXT NOT NULL DEFAULT 'manual', -- instagram/manual/web/other
    source_instagram_post_id INTEGER,
    source_url TEXT,
    source_note TEXT,

    -- 사용자 관리
    is_bookmarked BOOLEAN DEFAULT FALSE,
    is_participated BOOLEAN DEFAULT FALSE,
    user_note TEXT,

    -- 메타데이터
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (source_instagram_post_id) REFERENCES instagram_posts(id) ON DELETE SET NULL
);

-- 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_events_event_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);
CREATE INDEX IF NOT EXISTS idx_events_event_end ON events(event_end);
CREATE INDEX IF NOT EXISTS idx_events_source_type ON events(source_type);
CREATE INDEX IF NOT EXISTS idx_events_source_instagram_post_id ON events(source_instagram_post_id);
CREATE INDEX IF NOT EXISTS idx_events_is_bookmarked ON events(is_bookmarked);
