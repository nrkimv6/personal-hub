-- Google 검색 조건 저장 테이블
-- 검색 조건을 저장하고 나중에 재사용할 수 있도록 함

CREATE TABLE IF NOT EXISTS google_saved_searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 검색 조건
    name TEXT NOT NULL,                   -- 저장 이름 (예: "Python 블로그 검색")
    query TEXT NOT NULL,                  -- 검색 키워드
    date_filter TEXT,                     -- 날짜 필터 (1h, 24h, 1w, 1m, 1y)
    max_pages INTEGER DEFAULT 1,          -- 수집 페이지 수

    -- 옵션
    account_id INTEGER,                   -- 브라우저 프로필 ID
    is_favorite BOOLEAN DEFAULT FALSE,    -- 즐겨찾기

    -- 마지막 실행 정보
    last_search_id TEXT,                  -- 마지막 검색 결과 ID
    last_run_at TIMESTAMP,                -- 마지막 실행 시간
    last_result_count INTEGER,            -- 마지막 결과 수

    -- 메타
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE SET NULL
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_google_saved_searches_favorite ON google_saved_searches(is_favorite);
CREATE INDEX IF NOT EXISTS idx_google_saved_searches_last_run ON google_saved_searches(last_run_at);
CREATE INDEX IF NOT EXISTS idx_google_saved_searches_updated ON google_saved_searches(updated_at);
