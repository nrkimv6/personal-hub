-- Instagram Posts 추적 필드 추가
-- 신규/업데이트/중복 판별을 위한 필드

-- 1. created_at 추가 (처음 생성된 시간)
ALTER TABLE instagram_posts ADD COLUMN created_at DATETIME;

-- 2. updated_at 추가 (마지막 업데이트 시간)
ALTER TABLE instagram_posts ADD COLUMN updated_at DATETIME;

-- 3. last_seen_at 추가 (마지막으로 크롤링에서 발견된 시간)
ALTER TABLE instagram_posts ADD COLUMN last_seen_at DATETIME;

-- 4. last_seen_run_id 추가 (마지막으로 발견된 실행 ID)
ALTER TABLE instagram_posts ADD COLUMN last_seen_run_id INTEGER;

-- 기존 데이터 마이그레이션
-- collected_at을 created_at과 last_seen_at으로 복사
UPDATE instagram_posts
SET created_at = collected_at,
    last_seen_at = collected_at,
    last_seen_run_id = crawl_run_id
WHERE created_at IS NULL;

-- created_at에 NOT NULL 제약 추가 (기본값 설정)
-- SQLite는 ALTER TABLE로 NOT NULL 추가 불가, 새 테이블 생성 필요 없음 (기본값으로 채움)

-- 인덱스 추가
CREATE INDEX IF NOT EXISTS idx_instagram_posts_created_at ON instagram_posts(created_at);
CREATE INDEX IF NOT EXISTS idx_instagram_posts_updated_at ON instagram_posts(updated_at);
CREATE INDEX IF NOT EXISTS idx_instagram_posts_last_seen_at ON instagram_posts(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_instagram_posts_last_seen_run_id ON instagram_posts(last_seen_run_id);
