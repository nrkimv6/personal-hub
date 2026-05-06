-- Seed deterministic worktree hygiene report schedule.
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
    'worktree_hygiene_daily',
    'Worktree Hygiene Daily Report',
    'worktree_hygiene',
    '{"repo_root":"D:\\work\\project\\tools\\monitor-page","residue_retention_days":14,"auto_delete_residue":false,"report_only":true}',
    'cron',
    '0 8 * * *',
    1,
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
WHERE NOT EXISTS (
    SELECT 1 FROM task_schedules WHERE name = 'worktree_hygiene_daily'
);
