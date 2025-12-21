-- 033_crawl_run_details.sql
-- Instagram 크롤링 실행 기록 상세 정보 추가
-- 2025-12-21

-- 중단 사유 (stop_reason)
-- 가능한 값: 'max_posts_reached', 'duplicate_stop', 'max_refresh_after_duplicates',
--           'max_refresh_no_new_posts', 'scroll_exhausted', 'error', 'completed'
ALTER TABLE instagram_crawl_runs ADD COLUMN stop_reason TEXT;

-- 연속 중복 개수 (중단 시점)
ALTER TABLE instagram_crawl_runs ADD COLUMN duplicate_count INTEGER DEFAULT 0;

-- 실제 수행된 스크롤 횟수
ALTER TABLE instagram_crawl_runs ADD COLUMN scroll_performed INTEGER DEFAULT 0;

-- 새로고침 횟수
ALTER TABLE instagram_crawl_runs ADD COLUMN refresh_count INTEGER DEFAULT 0;

-- 수집 시점의 설정값 JSON (max_posts, duplicate_stop_count 등)
ALTER TABLE instagram_crawl_runs ADD COLUMN config_snapshot TEXT;

-- 기본값 설정 (기존 데이터)
UPDATE instagram_crawl_runs
SET stop_reason = CASE
    WHEN success = 1 THEN 'completed'
    WHEN error_message IS NOT NULL THEN 'error'
    ELSE 'completed'
END
WHERE stop_reason IS NULL;
