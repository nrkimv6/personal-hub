-- Migration: Create proxy_usage_logs table
-- Date: 2025-12-18
-- Description: 프록시 사용 이력 추적을 위한 테이블 생성
-- Note: 이 테이블은 메인 DB(monitor.db)에 생성됩니다.

-- 1. proxy_usage_logs 테이블 - 프록시 사용 이력
CREATE TABLE IF NOT EXISTS proxy_usage_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 연결 정보
    monitoring_event_id INTEGER,           -- monitoring_events.id (nullable, 최종 성공 시 연결)
    schedule_id INTEGER NOT NULL,          -- monitor_schedules.id

    -- 프록시 정보 (Note: proxies 테이블은 별도 DB에 있으므로 FK 불가)
    proxy_url TEXT NOT NULL,               -- 사용한 프록시 URL
    proxy_host TEXT,                       -- 프록시 호스트 (인덱싱/통계용)

    -- 시도 정보
    attempt_number INTEGER NOT NULL,       -- 시도 번호 (1, 2, 3...)
    request_id TEXT,                       -- 동일 요청 그룹 식별자 (UUID)

    -- 결과 정보
    success INTEGER NOT NULL DEFAULT 0,    -- 성공 여부 (0/1)
    http_status INTEGER,                   -- HTTP 응답 코드
    error_type TEXT,                       -- 에러 유형 (timeout, connection_error, http_403, etc.)
    error_message TEXT,                    -- 에러 메시지
    response_time_ms INTEGER,              -- 응답 시간 (밀리초)

    -- 컨텍스트
    target_url TEXT,                       -- 요청 대상 URL
    fetch_method TEXT,                     -- graphql_api, anonymous_api, html_scrape

    -- 타임스탬프
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- 외래키
    FOREIGN KEY (monitoring_event_id) REFERENCES monitoring_events(id) ON DELETE SET NULL,
    FOREIGN KEY (schedule_id) REFERENCES monitor_schedules(id) ON DELETE CASCADE
);

-- 인덱스
CREATE INDEX IF NOT EXISTS ix_proxy_usage_logs_timestamp ON proxy_usage_logs(timestamp);
CREATE INDEX IF NOT EXISTS ix_proxy_usage_logs_proxy_host ON proxy_usage_logs(proxy_host);
CREATE INDEX IF NOT EXISTS ix_proxy_usage_logs_request_id ON proxy_usage_logs(request_id);
CREATE INDEX IF NOT EXISTS ix_proxy_usage_logs_schedule_id ON proxy_usage_logs(schedule_id);
CREATE INDEX IF NOT EXISTS ix_proxy_usage_logs_success ON proxy_usage_logs(success);
CREATE INDEX IF NOT EXISTS ix_proxy_usage_logs_error_type ON proxy_usage_logs(error_type);
