-- Google 검색 결과 테이블
-- 각 검색 세션의 개별 검색 결과를 저장

CREATE TABLE IF NOT EXISTS google_search_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 검색 정보
    search_id TEXT NOT NULL,              -- 검색 세션 ID (UUID)
    query TEXT NOT NULL,                  -- 검색 키워드

    -- 결과 데이터
    rank INTEGER NOT NULL,                -- 검색 순위
    title TEXT NOT NULL,                  -- 제목
    url TEXT NOT NULL,                    -- 링크 URL
    display_url TEXT,                     -- 표시 URL
    snippet TEXT,                         -- 설명/요약
    publish_date TEXT,                    -- 게시일 (있는 경우)

    -- 필터 정보
    date_filter TEXT,                     -- 적용된 날짜 필터 (qdr:d, qdr:w 등)
    page_number INTEGER DEFAULT 1,        -- 페이지 번호

    -- 메타
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (search_id) REFERENCES google_search_history(search_id) ON DELETE CASCADE
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_google_search_results_search_id ON google_search_results(search_id);
CREATE INDEX IF NOT EXISTS idx_google_search_results_query ON google_search_results(query);
CREATE INDEX IF NOT EXISTS idx_google_search_results_created ON google_search_results(created_at);
CREATE INDEX IF NOT EXISTS idx_google_search_results_rank ON google_search_results(search_id, rank);
