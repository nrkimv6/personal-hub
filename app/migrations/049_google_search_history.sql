-- Google 검색 히스토리 테이블
-- 각 검색 세션의 메타데이터를 저장

CREATE TABLE IF NOT EXISTS google_search_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    search_id TEXT NOT NULL UNIQUE,       -- 검색 세션 ID (UUID)
    query TEXT NOT NULL,                  -- 검색 키워드
    date_filter TEXT,                     -- 날짜 필터
    max_pages INTEGER DEFAULT 1,          -- 수집 페이지 수

    -- 상태
    status TEXT DEFAULT 'pending',        -- pending, running, completed, failed
    total_results INTEGER DEFAULT 0,      -- 수집된 결과 수
    error_message TEXT,                   -- 에러 메시지

    -- 시간
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_google_search_history_search_id ON google_search_history(search_id);
CREATE INDEX IF NOT EXISTS idx_google_search_history_status ON google_search_history(status);
CREATE INDEX IF NOT EXISTS idx_google_search_history_created ON google_search_history(created_at);
