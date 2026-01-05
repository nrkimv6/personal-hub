-- Instagram posts에 source 컬럼 추가
-- 수집 출처 구분: "playwright" (기존 크롤러) | "extension" (브라우저 확장)

ALTER TABLE instagram_posts ADD COLUMN source VARCHAR(20) DEFAULT 'playwright';

-- 인덱스 추가
CREATE INDEX IF NOT EXISTS idx_instagram_posts_source ON instagram_posts(source);
