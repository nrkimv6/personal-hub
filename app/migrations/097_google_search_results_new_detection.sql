-- 검색결과 신규 감지 및 관리 기능 추가
-- 2026-02-10

-- google_search_results 테이블에 컬럼 추가
ALTER TABLE google_search_results ADD COLUMN is_new BOOLEAN DEFAULT 0;
ALTER TABLE google_search_results ADD COLUMN rank_change INTEGER DEFAULT NULL;
ALTER TABLE google_search_results ADD COLUMN prev_rank INTEGER DEFAULT NULL;
ALTER TABLE google_search_results ADD COLUMN is_read BOOLEAN DEFAULT 0;
ALTER TABLE google_search_results ADD COLUMN is_bookmarked BOOLEAN DEFAULT 0;
ALTER TABLE google_search_results ADD COLUMN memo TEXT DEFAULT NULL;

-- 인덱스 추가
CREATE INDEX IF NOT EXISTS idx_gsr_is_new ON google_search_results(is_new);
CREATE INDEX IF NOT EXISTS idx_gsr_is_bookmarked ON google_search_results(is_bookmarked);
CREATE INDEX IF NOT EXISTS idx_gsr_url ON google_search_results(url);

-- google_saved_searches 테이블에 알림 플래그 추가
ALTER TABLE google_saved_searches ADD COLUMN notify_on_new BOOLEAN DEFAULT 0;
