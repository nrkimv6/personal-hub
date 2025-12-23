-- 043: Instagram 게시물 활성화/비활성화 상태 추가
-- 실행: sqlite3 data\monitor.db < app\migrations\043_add_instagram_post_is_active.sql

-- is_active 컬럼 추가 (기본값 1 = 활성화)
ALTER TABLE instagram_posts ADD COLUMN is_active INTEGER DEFAULT 1;

-- 인덱스 추가 (필터링 성능 향상)
CREATE INDEX IF NOT EXISTS idx_instagram_posts_is_active ON instagram_posts(is_active);
