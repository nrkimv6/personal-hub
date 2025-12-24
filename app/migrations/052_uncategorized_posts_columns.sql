-- 052: UncategorizedPost 테이블 컬럼 추가 및 이름 변경
-- 날짜: 2024-12-24
-- 설명: Event와 일관성 맞추기 위해 컬럼 추가/변경

-- 1. 새 컬럼 추가 (Event와 동일한 이름)
ALTER TABLE uncategorized_posts ADD COLUMN event_start TEXT;
ALTER TABLE uncategorized_posts ADD COLUMN event_end TEXT;
ALTER TABLE uncategorized_posts ADD COLUMN announcement_date TEXT;
ALTER TABLE uncategorized_posts ADD COLUMN prizes TEXT;  -- JSON array
ALTER TABLE uncategorized_posts ADD COLUMN winner_count INTEGER;
ALTER TABLE uncategorized_posts ADD COLUMN purchase_required TEXT;

-- 2. 기존 데이터 마이그레이션 (start_date → event_start, end_date → event_end)
UPDATE uncategorized_posts SET event_start = start_date WHERE start_date IS NOT NULL;
UPDATE uncategorized_posts SET event_end = end_date WHERE end_date IS NOT NULL;

-- 3. 기존 컬럼은 유지 (SQLite 호환성, 추후 정리 가능)
-- DROP COLUMN은 SQLite 3.35+ 에서만 지원되므로 생략
