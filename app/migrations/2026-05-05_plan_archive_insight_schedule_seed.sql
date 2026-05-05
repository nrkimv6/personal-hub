-- Default Plan Archive insight batch schedule.
-- Disabled by default; operators can enable it after validating report volume.

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
