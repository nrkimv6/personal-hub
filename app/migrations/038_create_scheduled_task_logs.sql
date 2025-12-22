-- 스케줄 작업 실행 로그 테이블
-- Windows 작업 스케줄러 실행 이력 저장

CREATE TABLE IF NOT EXISTS scheduled_task_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_name TEXT NOT NULL,
    started_at DATETIME NOT NULL,
    finished_at DATETIME,
    status TEXT DEFAULT 'running',  -- running, success, failed
    duration_seconds INTEGER,
    records_processed INTEGER,
    error_message TEXT,
    details TEXT  -- JSON 형식 추가 정보
);

CREATE INDEX IF NOT EXISTS idx_task_logs_name_date
ON scheduled_task_logs(task_name, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_task_logs_started
ON scheduled_task_logs(started_at DESC);
