-- 077: RSS 피드 관리 테이블 및 writing_sources 확장
-- 2026-01-01

-- RSS 피드 소스 관리 테이블
CREATE TABLE IF NOT EXISTS writing_rss_feeds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL,
    url VARCHAR(500) NOT NULL UNIQUE,
    source_type VARCHAR(50) NOT NULL DEFAULT 'tistory',  -- 'tistory', 'naver_blog', 'medium', 'other'
    enabled INTEGER NOT NULL DEFAULT 1,
    last_fetched_at DATETIME,
    fetch_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_writing_rss_feeds_enabled ON writing_rss_feeds(enabled);
CREATE INDEX IF NOT EXISTS idx_writing_rss_feeds_source_type ON writing_rss_feeds(source_type);

-- writing_sources 테이블에 source_url, source_type 컬럼 추가
-- SQLite는 IF NOT EXISTS를 ALTER TABLE에서 지원하지 않으므로,
-- 이미 존재하면 에러가 발생할 수 있음 (무시 가능)
ALTER TABLE writing_sources ADD COLUMN source_url VARCHAR(500);
ALTER TABLE writing_sources ADD COLUMN source_type VARCHAR(50) DEFAULT 'manual';  -- 'rss', 'api', 'manual'
ALTER TABLE writing_sources ADD COLUMN content_hash VARCHAR(64);  -- 중복 체크용 SHA256 해시

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_writing_sources_source_type ON writing_sources(source_type);
CREATE INDEX IF NOT EXISTS idx_writing_sources_source_url ON writing_sources(source_url);
CREATE INDEX IF NOT EXISTS idx_writing_sources_content_hash ON writing_sources(content_hash);
