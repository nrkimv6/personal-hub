-- Plan Archive insight batch reports
-- SQLite-compatible DDL. PostgreSQL deployments can use the same logical
-- schema with JSON/JSONB capability selected by the migration runner.

CREATE TABLE IF NOT EXISTS plan_archive_insight_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    range_start DATETIME,
    range_end DATETIME,
    grouping VARCHAR(100) NOT NULL DEFAULT 'category',
    metrics_hash VARCHAR(64) NOT NULL,
    metrics_json JSON,
    evidence_json JSON,
    insight_json JSON,
    raw_response TEXT,
    provider VARCHAR(50) NOT NULL DEFAULT 'claude',
    model VARCHAR(100) NOT NULL DEFAULT '',
    status VARCHAR(30) NOT NULL DEFAULT 'pending',
    warning TEXT,
    error_message TEXT,
    llm_request_id INTEGER,
    created_at DATETIME,
    completed_at DATETIME,
    CONSTRAINT uq_plan_archive_insight_report_scope
        UNIQUE (range_start, range_end, grouping, provider, model, metrics_hash)
);

CREATE INDEX IF NOT EXISTS ix_plan_archive_insight_reports_status
    ON plan_archive_insight_reports(status);
CREATE INDEX IF NOT EXISTS ix_plan_archive_insight_reports_range
    ON plan_archive_insight_reports(range_start, range_end);
CREATE INDEX IF NOT EXISTS ix_plan_archive_insight_reports_grouping
    ON plan_archive_insight_reports(grouping);
CREATE INDEX IF NOT EXISTS ix_plan_archive_insight_reports_llm_request
    ON plan_archive_insight_reports(llm_request_id);

INSERT OR IGNORE INTO task_schedules
    (name, display_name, target_type, target_config, schedule_type, schedule_value, enabled, created_at, updated_at)
VALUES
    (
        'plan_archive_insight_weekly',
        'Plan Archive weekly insight batch',
        'plan_archive_insight_batch',
        '{"grouping":"category","days":30,"limit":20,"token_budget":3000}',
        'cron',
        '0 4 * * 1',
        0,
        CURRENT_TIMESTAMP,
        CURRENT_TIMESTAMP
    );
