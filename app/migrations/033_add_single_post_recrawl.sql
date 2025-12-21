-- 개별 게시물 재크롤링 기능 지원을 위한 컬럼 추가
-- instagram_crawl_requests 테이블에 request_type과 target_post_id 컬럼 추가

-- request_type: 요청 타입 ('feed': 피드 크롤링, 'single_post': 개별 게시물 재크롤링)
ALTER TABLE instagram_crawl_requests ADD COLUMN request_type TEXT DEFAULT 'feed' NOT NULL;

-- target_post_id: 재크롤링 대상 게시물 ID (single_post 타입일 때만 사용)
ALTER TABLE instagram_crawl_requests ADD COLUMN target_post_id INTEGER REFERENCES instagram_posts(id) ON DELETE SET NULL;

-- 인덱스 추가: request_type으로 빠른 조회
CREATE INDEX IF NOT EXISTS idx_instagram_crawl_requests_request_type ON instagram_crawl_requests(request_type);
