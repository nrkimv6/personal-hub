-- instagram_posts.crawl_run_id FK 제거
-- 작성일: 2025-12-31
-- 목적: instagram_crawl_runs 테이블 삭제 전 FK 제약 제거
--
-- ⚠️ 주의: 이 마이그레이션은 072, 073 보다 먼저 실행해야 합니다!
-- SQLite는 ALTER TABLE로 FK 수정이 안되므로 테이블 재생성 필요

-- 1. 기존 테이블 백업
CREATE TABLE IF NOT EXISTS instagram_posts_backup AS SELECT * FROM instagram_posts;

-- 2. 기존 테이블 삭제
DROP TABLE IF EXISTS instagram_posts;

-- 3. 새 테이블 생성 (crawl_run_id FK 제거)
CREATE TABLE instagram_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 기본 정보
    post_id TEXT UNIQUE NOT NULL,
    account TEXT NOT NULL,
    url TEXT,

    -- 콘텐츠
    caption TEXT,
    images TEXT,  -- JSON array

    -- 메타데이터
    posted_at DATETIME,
    display_time TEXT,
    is_ad INTEGER DEFAULT 0,
    likes INTEGER,
    comments INTEGER,
    duration REAL,
    is_reel BOOLEAN DEFAULT FALSE,
    music_title TEXT,
    music_artist TEXT,
    is_active INTEGER DEFAULT 1,
    post_type TEXT DEFAULT 'NORMAL',

    -- 분류 정보
    classified_type TEXT,
    classified_id INTEGER,
    classified_at DATETIME,

    -- 수집 정보 (FK 없는 레거시 컬럼)
    service_account_id INTEGER REFERENCES service_accounts(id) ON DELETE SET NULL,
    crawl_run_id INTEGER,  -- FK 제거됨 (레거시)
    collected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    schedule_run_id INTEGER REFERENCES crawl_schedule_runs(id) ON DELETE SET NULL
);

-- 4. 데이터 복원
INSERT INTO instagram_posts (
    id, post_id, account, url, caption, images,
    posted_at, display_time, is_ad, likes, comments,
    duration, is_reel, music_title, music_artist,
    is_active, post_type, classified_type, classified_id, classified_at,
    service_account_id, crawl_run_id, collected_at, schedule_run_id
)
SELECT
    id, post_id, account, url, caption, images,
    posted_at, display_time, is_ad, likes, comments,
    duration, is_reel, music_title, music_artist,
    is_active, post_type, classified_type, classified_id, classified_at,
    service_account_id, crawl_run_id, collected_at, schedule_run_id
FROM instagram_posts_backup;

-- 5. 백업 테이블 삭제
DROP TABLE IF EXISTS instagram_posts_backup;

-- 6. 인덱스 재생성
CREATE INDEX IF NOT EXISTS idx_instagram_posts_post_id ON instagram_posts(post_id);
CREATE INDEX IF NOT EXISTS idx_instagram_posts_account ON instagram_posts(account);
CREATE INDEX IF NOT EXISTS idx_instagram_posts_posted_at ON instagram_posts(posted_at);
CREATE INDEX IF NOT EXISTS idx_instagram_posts_collected_at ON instagram_posts(collected_at);
CREATE INDEX IF NOT EXISTS idx_instagram_posts_is_active ON instagram_posts(is_active);
CREATE INDEX IF NOT EXISTS idx_instagram_posts_post_type ON instagram_posts(post_type);
CREATE INDEX IF NOT EXISTS idx_instagram_posts_is_reel ON instagram_posts(is_reel);
CREATE INDEX IF NOT EXISTS idx_instagram_posts_classified_type ON instagram_posts(classified_type);
