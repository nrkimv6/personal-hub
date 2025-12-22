-- 크롤링 요청에 target_url 컬럼 추가 (URL로 단일 게시물 수집용)
-- 2024-12-22

-- target_url 컬럼 추가
ALTER TABLE instagram_crawl_requests ADD COLUMN target_url VARCHAR(500);
