-- 일별 통계 집계 테이블
-- 작성일: 2025-12-23
-- 목적: 상세 로그 삭제 전 일별 집계 데이터 보존

-- 프록시 일별 통계 (proxy_usage_logs 집계)
CREATE TABLE IF NOT EXISTS proxy_daily_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL,
    proxy_host TEXT NOT NULL,
    total_attempts INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,
    avg_response_time_ms REAL,
    min_response_time_ms REAL,
    max_response_time_ms REAL,
    error_types TEXT,  -- JSON: {"timeout": 5, "http_403": 3, ...}
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date, proxy_host)
);

CREATE INDEX IF NOT EXISTS idx_proxy_daily_stats_date
ON proxy_daily_stats(date);

CREATE INDEX IF NOT EXISTS idx_proxy_daily_stats_proxy_host
ON proxy_daily_stats(proxy_host);

-- 모니터링 일별 통계 (monitoring_events 집계)
CREATE TABLE IF NOT EXISTS monitoring_daily_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL,
    schedule_id INTEGER NOT NULL,
    check_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    available_detected INTEGER DEFAULT 0,  -- 예약 가능 슬롯 감지 횟수
    booking_triggered INTEGER DEFAULT 0,   -- 자동 예약 트리거 횟수
    booking_success INTEGER DEFAULT 0,     -- 예약 성공 횟수
    avg_response_time_ms REAL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date, schedule_id),
    FOREIGN KEY (schedule_id) REFERENCES monitor_schedules(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_monitoring_daily_stats_date
ON monitoring_daily_stats(date);

CREATE INDEX IF NOT EXISTS idx_monitoring_daily_stats_schedule_id
ON monitoring_daily_stats(schedule_id);

-- 유지보수 실행 로그 (기존 scheduled_task_logs 활용하되, 상세 결과 저장용)
CREATE TABLE IF NOT EXISTS maintenance_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date DATE NOT NULL,
    started_at DATETIME NOT NULL,
    finished_at DATETIME,
    status TEXT DEFAULT 'running',  -- running, success, failed

    -- 집계 결과
    proxy_stats_aggregated INTEGER DEFAULT 0,
    monitoring_stats_aggregated INTEGER DEFAULT 0,

    -- 정리 결과
    proxy_usage_logs_deleted INTEGER DEFAULT 0,
    proxy_check_history_deleted INTEGER DEFAULT 0,
    monitoring_events_deleted INTEGER DEFAULT 0,

    -- 최적화
    vacuum_executed INTEGER DEFAULT 0,  -- 0/1

    error_message TEXT,
    details TEXT,  -- JSON 형식 추가 정보

    UNIQUE(run_date)
);

CREATE INDEX IF NOT EXISTS idx_maintenance_runs_date
ON maintenance_runs(run_date DESC);
