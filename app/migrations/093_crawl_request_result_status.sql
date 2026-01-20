-- CrawlRequest에 result_status 필드 추가
-- 크롤링 결과가 신규인지, 업데이트인지, 중복인지 추적

ALTER TABLE crawl_requests ADD COLUMN result_status VARCHAR(20);
-- 'created': 신규 추가
-- 'updated': 기존 포스트 업데이트
-- 'unchanged': 중복 (변경 없음)
-- NULL: 아직 처리 안됨 또는 실패

CREATE INDEX IF NOT EXISTS idx_crawl_requests_result_status ON crawl_requests(result_status);
