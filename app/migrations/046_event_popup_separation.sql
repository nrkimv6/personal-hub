-- 046: Event/Popup 분리 및 Uncategorized 테이블 생성
-- 날짜: 2024-12-24
-- 설명: Instagram LLM 분석 결과를 Event/Popup/Uncategorized로 분리

-- 1. Popup 테이블 생성
CREATE TABLE IF NOT EXISTS popups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    thumbnail_url TEXT,

    -- 기간
    start_date TEXT,
    end_date TEXT,

    -- 위치 (팝업 핵심 정보)
    venue_name TEXT,
    address TEXT,
    floor_info TEXT,

    -- 운영 정보
    operating_hours TEXT,
    admission_fee TEXT,
    reservation_required INTEGER DEFAULT 0,
    reservation_url TEXT,

    -- 브랜드/주최
    brand TEXT,
    organizer TEXT,
    collaboration TEXT,

    -- 상세
    summary TEXT,
    highlights TEXT,  -- JSON array
    official_url TEXT,
    additional_urls TEXT,  -- JSON array

    -- 출처
    source_type TEXT NOT NULL DEFAULT 'instagram',
    source_instagram_post_id INTEGER REFERENCES instagram_posts(id) ON DELETE SET NULL,
    source_instagram_url TEXT,
    source_instagram_account TEXT,

    -- 사용자 관리
    is_bookmarked INTEGER DEFAULT 0,
    is_visited INTEGER DEFAULT 0,
    user_note TEXT,

    -- 상태
    status TEXT DEFAULT 'active',

    -- 메타데이터
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Popup 인덱스
CREATE INDEX IF NOT EXISTS idx_popups_start_date ON popups(start_date);
CREATE INDEX IF NOT EXISTS idx_popups_end_date ON popups(end_date);
CREATE INDEX IF NOT EXISTS idx_popups_status ON popups(status);
CREATE INDEX IF NOT EXISTS idx_popups_source_type ON popups(source_type);
CREATE INDEX IF NOT EXISTS idx_popups_source_instagram_post_id ON popups(source_instagram_post_id);
CREATE INDEX IF NOT EXISTS idx_popups_is_bookmarked ON popups(is_bookmarked);

-- 2. Uncategorized 테이블 생성
CREATE TABLE IF NOT EXISTS uncategorized_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 분류 정보
    original_tag TEXT,

    -- 기본 정보
    title TEXT,
    thumbnail_url TEXT,
    summary TEXT,
    organizer TEXT,

    -- 기간
    start_date TEXT,
    end_date TEXT,

    -- URL
    urls TEXT,  -- JSON array

    -- 출처
    source_instagram_post_id INTEGER NOT NULL REFERENCES instagram_posts(id) ON DELETE SET NULL,
    source_instagram_url TEXT,
    source_instagram_account TEXT,

    -- 수동 재분류
    reclassified_as TEXT,
    reclassified_id INTEGER,
    reclassified_at TEXT,

    -- 메타데이터
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Uncategorized 인덱스
CREATE INDEX IF NOT EXISTS idx_uncategorized_original_tag ON uncategorized_posts(original_tag);
CREATE INDEX IF NOT EXISTS idx_uncategorized_source_instagram_post_id ON uncategorized_posts(source_instagram_post_id);
CREATE INDEX IF NOT EXISTS idx_uncategorized_reclassified_as ON uncategorized_posts(reclassified_as);

-- 3. Event 테이블에 컬럼 추가
ALTER TABLE events ADD COLUMN thumbnail_url TEXT;
ALTER TABLE events ADD COLUMN source_instagram_url TEXT;
ALTER TABLE events ADD COLUMN source_instagram_account TEXT;

-- 4. InstagramPost 테이블에 분류 참조 컬럼 추가
ALTER TABLE instagram_posts ADD COLUMN classified_type TEXT;
ALTER TABLE instagram_posts ADD COLUMN classified_id INTEGER;

-- InstagramPost 분류 인덱스
CREATE INDEX IF NOT EXISTS idx_instagram_posts_classified_type ON instagram_posts(classified_type);
