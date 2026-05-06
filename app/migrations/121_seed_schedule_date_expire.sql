-- Migration 121: schedule_date_expire_daily 스케줄 seed
-- 매일 KST 01:00에 과거 날짜 모니터링 스케줄 is_enabled=false 일괄 처리

INSERT INTO task_schedules (
    name, display_name, target_type, target_config,
    schedule_type, schedule_value, enabled,
    created_at, updated_at
) VALUES (
    'schedule_date_expire_daily',
    '과거 날짜 모니터링 스케줄 자동 비활성화 (매일 01:00)',
    'schedule_date_expire',
    '{}',
    'cron',
    '{"time": "01:00"}',
    true,
    now(),
    now()
) ON CONFLICT (name) DO NOTHING;
