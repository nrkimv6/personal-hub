-- 레거시 Instagram 테이블 삭제
-- 작성일: 2025-12-31
-- 목적: 사용되지 않는 레거시 테이블 정리
--
-- ⚠️ 주의: 이 마이그레이션은 반드시 072_cleanup_worker_status_fk.sql 실행 후 실행하세요!
--
-- 삭제 대상:
-- 1. instagram_crawl_events - FK가 instagram_crawl_runs를 참조
-- 2. instagram_llm_worker_status - FK가 instagram_llm_classification_requests를 참조
-- 3. instagram_crawl_runs - FK 의존성 해제됨
-- 4. instagram_llm_classification_requests - FK 의존성 해제됨
-- 5. instagram_crawl_requests - 대체됨 (crawl_requests)
-- 6. instagram_schedule_config - 대체됨 (crawl_schedules.target_config)
-- 7. universal_crawl_requests - 대체됨 (crawl_requests)

-- 1. instagram_crawl_events (FK가 instagram_crawl_runs를 참조)
DROP TABLE IF EXISTS instagram_crawl_events;

-- 2. instagram_llm_worker_status (FK가 instagram_llm_classification_requests를 참조)
DROP TABLE IF EXISTS instagram_llm_worker_status;

-- 3. instagram_crawl_runs (이제 FK 의존성 없음)
DROP TABLE IF EXISTS instagram_crawl_runs;

-- 4. instagram_llm_classification_requests (이제 FK 의존성 없음)
DROP TABLE IF EXISTS instagram_llm_classification_requests;

-- 5. instagram_crawl_requests
DROP TABLE IF EXISTS instagram_crawl_requests;

-- 6. instagram_schedule_config
DROP TABLE IF EXISTS instagram_schedule_config;

-- 7. universal_crawl_requests
DROP TABLE IF EXISTS universal_crawl_requests;
