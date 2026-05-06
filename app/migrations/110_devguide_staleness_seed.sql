-- Seed devguide_staleness and disable the legacy plan_requirements_sync schedule.

INSERT OR IGNORE INTO task_schedules (
    name,
    display_name,
    target_type,
    target_config,
    schedule_type,
    schedule_value,
    enabled,
    created_at,
    updated_at
) VALUES (
    'devguide_staleness_daily',
    'Dev-guide Staleness 감지 (매일 03:30)',
    'devguide_staleness',
    '{}',
    'cron',
    '{"time": "03:30"}',
    1,
    datetime('now'),
    datetime('now')
);

UPDATE task_schedules
SET enabled = 0,
    updated_at = datetime('now')
WHERE target_type = 'plan_requirements_sync';
