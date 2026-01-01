-- 076: Keyword Statistics Tables
-- 글쓰기 소스에서 추출한 키워드 통계

-- 키워드 통계 테이블
CREATE TABLE IF NOT EXISTS keyword_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL,
    frequency INTEGER NOT NULL DEFAULT 1,        -- 총 출현 횟수
    source_count INTEGER NOT NULL DEFAULT 1,    -- 키워드가 나온 글 개수
    avg_per_source REAL,                         -- 글당 평균 출현 (frequency / source_count)
    category TEXT,                               -- 카테고리별 분석용 (NULL이면 전체)
    analyzed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(keyword, category)
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_keyword_stats_keyword ON keyword_stats(keyword);
CREATE INDEX IF NOT EXISTS idx_keyword_stats_frequency ON keyword_stats(frequency DESC);
CREATE INDEX IF NOT EXISTS idx_keyword_stats_source_count ON keyword_stats(source_count DESC);
CREATE INDEX IF NOT EXISTS idx_keyword_stats_category ON keyword_stats(category);
CREATE INDEX IF NOT EXISTS idx_keyword_stats_analyzed_at ON keyword_stats(analyzed_at);
