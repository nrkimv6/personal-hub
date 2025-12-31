-- 078: 검색 쿼리 관리 테이블
-- 2026-01-01

-- 검색 쿼리 테이블
CREATE TABLE IF NOT EXISTS writing_search_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query VARCHAR(200) NOT NULL,
    source_type VARCHAR(50) NOT NULL DEFAULT 'naver',  -- 'naver', 'kakao', 'google'
    search_target VARCHAR(50) NOT NULL DEFAULT 'blog',  -- 'blog', 'cafe', 'news'
    enabled INTEGER NOT NULL DEFAULT 1,
    priority INTEGER NOT NULL DEFAULT 0,  -- 높을수록 먼저 검색
    last_searched_at DATETIME,
    result_count INTEGER NOT NULL DEFAULT 0,  -- 누적 결과 수
    success_count INTEGER NOT NULL DEFAULT 0,  -- 성공 횟수
    error_count INTEGER NOT NULL DEFAULT 0,  -- 실패 횟수
    last_error TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_writing_search_queries_enabled
    ON writing_search_queries(enabled);
CREATE INDEX IF NOT EXISTS idx_writing_search_queries_source_type
    ON writing_search_queries(source_type);
CREATE INDEX IF NOT EXISTS idx_writing_search_queries_priority
    ON writing_search_queries(priority DESC);

-- 기본 검색 쿼리 삽입 (네이버 블로그)
INSERT OR IGNORE INTO writing_search_queries (query, source_type, search_target, priority) VALUES
    ('시니어 에세이', 'naver', 'blog', 10),
    ('60대 일상', 'naver', 'blog', 9),
    ('은퇴 후 삶', 'naver', 'blog', 9),
    ('손주 이야기', 'naver', 'blog', 8),
    ('부모님 추억', 'naver', 'blog', 8),
    ('고향 생각', 'naver', 'blog', 7),
    ('계절 단상', 'naver', 'blog', 7),
    ('인생 회고', 'naver', 'blog', 7),
    ('따뜻한 글', 'naver', 'blog', 6),
    ('잔잔한 에세이', 'naver', 'blog', 6),
    ('마음 위로', 'naver', 'blog', 5),
    ('감사 일기', 'naver', 'blog', 5),
    ('어머니 에세이', 'naver', 'blog', 5),
    ('아버지 추억', 'naver', 'blog', 5),
    ('부부 일상', 'naver', 'blog', 4);

-- 카카오 블로그 쿼리
INSERT OR IGNORE INTO writing_search_queries (query, source_type, search_target, priority) VALUES
    ('시니어 에세이', 'kakao', 'blog', 8),
    ('60대 일상', 'kakao', 'blog', 7),
    ('은퇴 생활', 'kakao', 'blog', 7),
    ('가족 이야기', 'kakao', 'blog', 6),
    ('추억 에세이', 'kakao', 'blog', 6);
