-- 027_add_timing_breakdown.sql
-- 모니터링 실행 타이밍 상세 기록 필드 추가
-- 2025-12-16

-- GraphQL 호출 시간 (ms) - 프록시 경유 포함
ALTER TABLE monitoring_events ADD COLUMN graphql_time_ms REAL;

-- 프록시 재시도 횟수
ALTER TABLE monitoring_events ADD COLUMN proxy_retry_count INTEGER;

-- 예약 실행 시간 (ms) - 탭 생성, 폼 제출 등
ALTER TABLE monitoring_events ADD COLUMN booking_time_ms REAL;

-- 예약 시도 슬롯 수
ALTER TABLE monitoring_events ADD COLUMN booking_attempt_count INTEGER;
