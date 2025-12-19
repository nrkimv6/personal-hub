-- 029_add_performance_indexes.sql
-- 성능 최적화를 위한 복합 인덱스 추가
-- 2025-12-19

-- 모니터링 스케줄: 활성화된 일정 날짜순 조회 최적화
CREATE INDEX IF NOT EXISTS idx_monitor_schedules_enabled_date
ON monitor_schedules(is_enabled, date DESC);

-- 모니터링 이벤트: 스케줄+상태 필터링 최적화
CREATE INDEX IF NOT EXISTS idx_monitoring_events_schedule_status
ON monitoring_events(schedule_id, status);

-- 프록시 사용 로그: 호스트+시간 조회 최적화
CREATE INDEX IF NOT EXISTS idx_proxy_usage_logs_proxy_host_timestamp
ON proxy_usage_logs(proxy_host, timestamp DESC);

-- 프록시 사용 로그: 요청별 시도 추적 최적화
CREATE INDEX IF NOT EXISTS idx_proxy_usage_logs_request_attempt
ON proxy_usage_logs(request_id, attempt_number);

-- 프록시 사용 로그: 스케줄별 이력 조회 최적화
CREATE INDEX IF NOT EXISTS idx_proxy_usage_logs_schedule_timestamp
ON proxy_usage_logs(schedule_id, timestamp DESC);

-- 모니터링 이벤트: 타임스탬프+상태 (시간대별 상태 필터링)
CREATE INDEX IF NOT EXISTS idx_monitoring_events_timestamp_status
ON monitoring_events(timestamp DESC, status);
