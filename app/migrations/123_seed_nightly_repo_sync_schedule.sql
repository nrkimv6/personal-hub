-- Seed nightly main/plans sync automation schedule.
INSERT INTO task_schedules (
    name,
    display_name,
    target_type,
    target_config,
    schedule_type,
    schedule_value,
    enabled,
    created_at,
    updated_at
)
SELECT
    'nightly_repo_sync_daily',
    'Nightly Main/Plans Sync',
    'nightly_repo_sync',
    '{"repo_root":"D:\\work\\project\\tools\\monitor-page","allow_mutation":true}',
    'cron',
    '0 3 * * *',
    1,
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
WHERE NOT EXISTS (
    SELECT 1 FROM task_schedules WHERE name = 'nightly_repo_sync_daily'
);
