-- Instagram 크롤링 실행 기록 테이블 (먼저 생성 - instagram_posts가 참조함)
CREATE TABLE IF NOT EXISTS instagram_crawl_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 실행 정보
    account_id INTEGER NOT NULL,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME,

    -- 결과
    success INTEGER DEFAULT 0,  -- SQLite boolean
    total_collected INTEGER DEFAULT 0,
    new_saved INTEGER DEFAULT 0,
    error_message TEXT,

    -- 외래 키
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
);

-- Instagram 게시물 테이블
CREATE TABLE IF NOT EXISTS instagram_posts (
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
    is_ad INTEGER DEFAULT 0,  -- SQLite boolean

    -- 수집 정보
    account_id INTEGER,  -- 수집에 사용된 계정
    crawl_run_id INTEGER,  -- 수집 실행 ID
    collected_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- 외래 키
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE SET NULL,
    FOREIGN KEY (crawl_run_id) REFERENCES instagram_crawl_runs(id) ON DELETE SET NULL
);

-- Instagram 스케줄 설정 테이블
CREATE TABLE IF NOT EXISTS instagram_schedule_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 설정
    enabled INTEGER DEFAULT 1,  -- SQLite boolean
    daily_runs INTEGER DEFAULT 3,
    time_windows TEXT DEFAULT '[{"start": "07:00", "end": "10:00"}, {"start": "12:00", "end": "15:00"}, {"start": "19:00", "end": "23:00"}]',
    max_posts INTEGER DEFAULT 20,
    scroll_count INTEGER DEFAULT 3,

    -- 메타
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_instagram_posts_account ON instagram_posts(account);
CREATE INDEX IF NOT EXISTS idx_instagram_posts_posted_at ON instagram_posts(posted_at);
CREATE INDEX IF NOT EXISTS idx_instagram_posts_collected_at ON instagram_posts(collected_at);
CREATE INDEX IF NOT EXISTS idx_instagram_posts_crawl_run_id ON instagram_posts(crawl_run_id);
CREATE INDEX IF NOT EXISTS idx_instagram_crawl_runs_account_id ON instagram_crawl_runs(account_id);
CREATE INDEX IF NOT EXISTS idx_instagram_crawl_runs_started_at ON instagram_crawl_runs(started_at);

-- 기본 스케줄 설정 삽입 (없으면)
INSERT OR IGNORE INTO instagram_schedule_config (id, enabled, daily_runs, time_windows, max_posts, scroll_count)
VALUES (1, 1, 3, '[{"start": "07:00", "end": "10:00"}, {"start": "12:00", "end": "15:00"}, {"start": "19:00", "end": "23:00"}]', 20, 3);
