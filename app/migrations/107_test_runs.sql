-- 107_test_runs.sql
-- pytest 자동 실행 이력 테이블 생성
-- 2026-02-26

CREATE TABLE IF NOT EXISTS test_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    started_at DATETIME NOT NULL DEFAULT (datetime('now')),
    finished_at DATETIME,

    status VARCHAR(20) NOT NULL DEFAULT 'running',
    -- running / completed / failed

    total_tests INTEGER DEFAULT 0,
    passed INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    skipped INTEGER DEFAULT 0,

    duration_seconds REAL,

    schedule_run_id INTEGER REFERENCES task_schedule_runs(id) ON DELETE SET NULL,

    log_file_path VARCHAR(500),
    xml_file_path VARCHAR(500),

    triggered_by VARCHAR(20) NOT NULL DEFAULT 'manual',
    -- scheduler / manual / api

    test_path VARCHAR(500) DEFAULT 'tests/',
    extra_args TEXT
);

CREATE INDEX IF NOT EXISTS ix_test_runs_status ON test_runs (status);
CREATE INDEX IF NOT EXISTS ix_test_runs_started_at ON test_runs (started_at);
CREATE INDEX IF NOT EXISTS ix_test_runs_status_started ON test_runs (status, started_at);


CREATE TABLE IF NOT EXISTS test_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    test_run_id INTEGER NOT NULL REFERENCES test_runs(id) ON DELETE CASCADE,

    test_name VARCHAR(1000) NOT NULL,
    -- 예: tests/test_foo.py::TestClass::test_method

    status VARCHAR(20) NOT NULL,
    -- passed / failed / error / skipped

    duration_seconds REAL DEFAULT 0.0,

    error_message TEXT,
    traceback TEXT,

    fix_plan TEXT,
    llm_request_id INTEGER REFERENCES llm_requests(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_test_results_test_run_id ON test_results (test_run_id);
CREATE INDEX IF NOT EXISTS ix_test_results_status ON test_results (status);
CREATE INDEX IF NOT EXISTS ix_test_results_run_status ON test_results (test_run_id, status);
CREATE INDEX IF NOT EXISTS ix_test_results_duration ON test_results (test_run_id, duration_seconds);
