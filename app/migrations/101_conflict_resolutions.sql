-- 101_conflict_resolutions.sql
-- conflict 자동 해결 이력 저장 테이블

CREATE TABLE IF NOT EXISTS conflict_resolutions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    runner_id TEXT NOT NULL,
    branch TEXT NOT NULL,
    conflict_files TEXT NOT NULL,
    resolved_files TEXT,
    failed_files TEXT,
    strategy TEXT,
    success BOOLEAN NOT NULL DEFAULT 0,
    duration_ms INTEGER,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_conflict_resolutions_runner ON conflict_resolutions (runner_id);
