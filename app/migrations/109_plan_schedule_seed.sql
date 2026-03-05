-- plan_archive_analyze / plan_requirements_sync 스케줄 seed
-- TaskSchedule 레코드 2개 INSERT (이미 존재하면 무시)

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
    'plan_archive_analyze_daily',
    'Plan Archive LLM 분석 (매일 02:10)',
    'plan_archive_analyze',
    '{}',
    'cron',
    '{"time": "02:10"}',
    1,
    datetime('now'),
    datetime('now')
);

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
    'plan_requirements_sync_daily',
    'Plan 요구사항 문서 동기화 (매일 03:30)',
    'plan_requirements_sync',
    '{}',
    'cron',
    '{"time": "03:30"}',
    1,
    datetime('now'),
    datetime('now')
);
