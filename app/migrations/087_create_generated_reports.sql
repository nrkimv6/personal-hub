-- 087: Create generated_reports table

CREATE TABLE IF NOT EXISTS generated_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_type VARCHAR(50) NOT NULL,
    period_start DATETIME NOT NULL,
    period_end DATETIME NOT NULL,
    title VARCHAR(200),
    content TEXT NOT NULL,
    summary TEXT,
    statistics TEXT,
    llm_request_id INTEGER REFERENCES llm_requests(id),
    schedule_run_id INTEGER REFERENCES task_schedule_runs(id),
    generated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    format VARCHAR(20) DEFAULT 'markdown',
    deleted_at DATETIME
);

CREATE INDEX idx_reports_type ON generated_reports(report_type);
CREATE INDEX idx_reports_period_end ON generated_reports(period_end);
CREATE INDEX idx_reports_generated_at ON generated_reports(generated_at);
