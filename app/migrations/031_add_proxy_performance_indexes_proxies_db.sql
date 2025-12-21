-- 프록시 API 성능 개선을 위한 인덱스 추가 (proxies.db용)
-- 작성일: 2025-12-21
-- 관련 계획서: docs/proxy/2025-12-21-proxy-api-performance-optimization.md
-- 주의: 이 파일은 proxies.db에 별도로 실행해야 합니다.

-- proxy_check_history 테이블 인덱스 추가

-- 1. 오늘 검증 통계용 커버링 인덱스
-- get_stats() 쿼리 최적화: checked_at 범위 필터 + is_valid 집계
CREATE INDEX IF NOT EXISTS idx_history_checked_valid
ON proxy_check_history(checked_at, is_valid);

-- 2. 평균 응답시간 계산용 커버링 인덱스
-- add_check_history() 쿼리 최적화: proxy_id + is_valid 필터 + response_time 집계
CREATE INDEX IF NOT EXISTS idx_history_proxy_valid_response
ON proxy_check_history(proxy_id, is_valid, response_time);
