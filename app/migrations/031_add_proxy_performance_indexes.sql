-- 프록시 API 성능 개선을 위한 인덱스 추가 (monitor.db용)
-- 작성일: 2025-12-21
-- 관련 계획서: docs/proxy/2025-12-21-proxy-api-performance-optimization.md

-- proxy_usage_logs 테이블 인덱스 추가

-- 1. 기간별 프록시 통계용 복합 인덱스
-- get_usage_stats() 쿼리 최적화: timestamp 범위 + proxy_host 그룹핑 + success 집계
CREATE INDEX IF NOT EXISTS idx_usage_timestamp_host_success
ON proxy_usage_logs(timestamp, proxy_host, success);

-- 2. 에러 유형별 조회 최적화 (실패 건만)
-- get_failed_proxies(), get_usage_stats() 에러 유형 조회 최적화
CREATE INDEX IF NOT EXISTS idx_usage_host_error_timestamp
ON proxy_usage_logs(proxy_host, error_type, timestamp)
WHERE success = 0;
