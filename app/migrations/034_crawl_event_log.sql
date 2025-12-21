-- 034_crawl_event_log.sql
-- Instagram 크롤링 이벤트 로그 테이블
-- 2025-12-21

CREATE TABLE IF NOT EXISTS instagram_crawl_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    crawl_run_id INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,  -- 'scroll', 'post_saved', 'duplicate', 'refresh', 'stop'
    message TEXT,
    details TEXT,  -- JSON (post_url, duplicate_count, etc.)
    FOREIGN KEY (crawl_run_id) REFERENCES instagram_crawl_runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_crawl_event_run_id ON instagram_crawl_events(crawl_run_id);
CREATE INDEX IF NOT EXISTS idx_crawl_event_type ON instagram_crawl_events(event_type);
CREATE INDEX IF NOT EXISTS idx_crawl_event_timestamp ON instagram_crawl_events(timestamp);
