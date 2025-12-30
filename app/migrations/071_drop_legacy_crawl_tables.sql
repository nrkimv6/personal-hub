-- 레거시 크롤링 테이블 삭제 (실행용)
-- 작성일: 2025-12-30
-- 목적: 데이터 마이그레이션 완료 후 레거시 테이블 제거
--
-- ⚠️ 주의: 이 마이그레이션은 반드시 아래 조건을 확인 후 실행하세요!
--
-- 실행 전 확인 사항:
-- 1. 069_migrate_crawl_data.sql이 정상 실행되었는지 확인
-- 2. 워커들이 새 테이블(crawl_requests, crawl_schedules, crawl_schedule_runs)을 사용하는지 확인
-- 3. API가 새 테이블을 정상적으로 조회하는지 확인
--
-- 데이터 정합성 확인 쿼리:
-- SELECT COUNT(*) FROM instagram_crawl_requests;
-- SELECT COUNT(*) FROM crawl_requests WHERE url_type = 'instagram';
-- SELECT COUNT(*) FROM instagram_schedule_config;
-- SELECT COUNT(*) FROM crawl_schedules WHERE target_type = 'instagram_feed';
-- SELECT COUNT(*) FROM instagram_crawl_runs;
-- SELECT COUNT(*) FROM crawl_schedule_runs;

-- 1. instagram_posts에서 레거시 FK 컬럼 제거
-- SQLite는 ALTER TABLE DROP COLUMN을 지원하지 않으므로 테이블 재생성 필요
-- 대신 해당 컬럼은 무시하고 그대로 둠 (orphan 데이터)

-- 2. 레거시 Instagram 크롤 요청 테이블 삭제
DROP TABLE IF EXISTS instagram_crawl_requests;

-- 3. 레거시 Instagram 크롤 실행 이력 테이블 삭제
DROP TABLE IF EXISTS instagram_crawl_runs;

-- 4. 레거시 Instagram 스케줄 설정 테이블 삭제
DROP TABLE IF EXISTS instagram_schedule_config;

-- 5. 레거시 Universal 크롤 요청 테이블 삭제
DROP TABLE IF EXISTS universal_crawl_requests;

-- 완료 메시지
-- 마이그레이션 완료 후 다음 모델/서비스 파일도 제거할 수 있습니다:
-- - app/models/instagram_crawl_request.py
-- - app/models/instagram_crawl_run.py
-- - app/models/instagram_schedule_config.py
-- - app/models/universal_crawl.py (UniversalCrawlRequest 부분)
-- - app/services/instagram_crawl_request_service.py (있다면)
