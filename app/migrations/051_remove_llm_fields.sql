-- 051: InstagramPost 테이블에서 llm_* 컬럼 제거
-- 날짜: 2024-12-24
-- 설명: Event/Popup 테이블로 데이터가 마이그레이션되었으므로 llm_* 컬럼 제거
-- 참고: 047_migrate_llm_data.sql에서 데이터 마이그레이션 완료됨
-- 요구사항: SQLite 3.35.0+ (DROP COLUMN 지원)

-- llm_* 컬럼 삭제
-- 순서: 의존성 없이 독립적으로 삭제 가능

ALTER TABLE instagram_posts DROP COLUMN llm_status;
ALTER TABLE instagram_posts DROP COLUMN llm_tag;
ALTER TABLE instagram_posts DROP COLUMN llm_purchase_required;
ALTER TABLE instagram_posts DROP COLUMN llm_prizes;
ALTER TABLE instagram_posts DROP COLUMN llm_winner_count;
ALTER TABLE instagram_posts DROP COLUMN llm_event_start;
ALTER TABLE instagram_posts DROP COLUMN llm_event_end;
ALTER TABLE instagram_posts DROP COLUMN llm_announcement_date;
ALTER TABLE instagram_posts DROP COLUMN llm_urls;
ALTER TABLE instagram_posts DROP COLUMN llm_organizer;
ALTER TABLE instagram_posts DROP COLUMN llm_summary;
ALTER TABLE instagram_posts DROP COLUMN llm_location;
ALTER TABLE instagram_posts DROP COLUMN llm_analyzed_at;

-- 인덱스 정리 (이미 존재하지 않으면 에러 무시)
-- DROP INDEX IF EXISTS idx_instagram_posts_llm_status;
-- DROP INDEX IF EXISTS idx_instagram_posts_llm_tag;
