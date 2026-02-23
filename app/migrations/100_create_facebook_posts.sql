-- 100: Facebook Posts 테이블 생성
-- 작성일: 2026-02-23

CREATE TABLE IF NOT EXISTS facebook_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 기본 정보
    post_id VARCHAR NOT NULL UNIQUE,
    account VARCHAR NOT NULL,
    url VARCHAR,

    -- 콘텐츠
    caption TEXT,
    images TEXT DEFAULT '[]',  -- JSON

    -- 메타데이터
    posted_at DATETIME,
    display_time VARCHAR,

    -- Facebook 특화: Reactions
    reactions TEXT DEFAULT '{}',  -- JSON {"like": 10, "love": 5, ...}
    total_reactions INTEGER DEFAULT 0,
    shares INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,

    -- 게시물 유형
    post_type VARCHAR DEFAULT 'NORMAL',
    original_post_url VARCHAR,
    link_preview TEXT,  -- JSON {"title", "description", "image", "domain"}

    -- 소스 유형
    source_type VARCHAR,
    group_id VARCHAR,
    group_name VARCHAR,
    page_id VARCHAR,
    page_name VARCHAR,

    -- 수집 정보
    service_account_id INTEGER REFERENCES service_accounts(id) ON DELETE SET NULL,
    crawl_run_id INTEGER,
    collected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    source VARCHAR(20) DEFAULT 'playwright',

    -- 추적 정보
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME,
    last_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen_run_id INTEGER,

    -- 활성화 상태
    is_active INTEGER DEFAULT 1,

    -- 분류 결과
    classified_type VARCHAR,
    classified_id INTEGER,
    classified_at DATETIME
);

-- 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_facebook_posts_post_id ON facebook_posts(post_id);
CREATE INDEX IF NOT EXISTS idx_facebook_posts_account ON facebook_posts(account);
CREATE INDEX IF NOT EXISTS idx_facebook_posts_posted_at ON facebook_posts(posted_at);
CREATE INDEX IF NOT EXISTS idx_facebook_posts_post_type ON facebook_posts(post_type);
CREATE INDEX IF NOT EXISTS idx_facebook_posts_source_type ON facebook_posts(source_type);
CREATE INDEX IF NOT EXISTS idx_facebook_posts_collected_at ON facebook_posts(collected_at);
CREATE INDEX IF NOT EXISTS idx_facebook_posts_created_at ON facebook_posts(created_at);
CREATE INDEX IF NOT EXISTS idx_facebook_posts_last_seen_at ON facebook_posts(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_facebook_posts_last_seen_run_id ON facebook_posts(last_seen_run_id);
CREATE INDEX IF NOT EXISTS idx_facebook_posts_is_active ON facebook_posts(is_active);
CREATE INDEX IF NOT EXISTS idx_facebook_posts_classified_type ON facebook_posts(classified_type);
CREATE INDEX IF NOT EXISTS idx_facebook_posts_classified_at ON facebook_posts(classified_at);
