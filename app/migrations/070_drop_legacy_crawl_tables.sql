-- 레거시 크롤링 테이블 삭제
-- 작성일: 2025-12-29
-- 목적: 데이터 마이그레이션 완료 후 기존 테이블 삭제
--
-- ⚠️ 주의: 이 마이그레이션은 069_migrate_crawl_data.sql 실행 및
-- 데이터 정합성 확인 후에만 실행해야 합니다.
--
-- 실행 전 확인 사항:
-- 1. crawl_requests에 모든 단건 요청이 이관되었는지 확인
-- 2. crawl_schedules에 모든 스케줄이 이관되었는지 확인
-- 3. crawl_schedule_runs에 모든 실행 이력이 이관되었는지 확인
-- 4. instagram_posts.schedule_run_id FK가 올바르게 매핑되었는지 확인

-- 레거시 Instagram 테이블 삭제
-- DROP TABLE IF EXISTS instagram_crawl_requests;
-- DROP TABLE IF EXISTS instagram_crawl_runs;
-- DROP TABLE IF EXISTS instagram_schedule_config;

-- 레거시 Universal Crawl 테이블 삭제
-- DROP TABLE IF EXISTS universal_crawl_requests;

-- 주석 처리된 상태로 유지
-- 실제 삭제 시 위 DROP 문의 주석을 제거하고 실행
