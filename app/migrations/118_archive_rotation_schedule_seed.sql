-- Migration 118: archive_rotation_daily 스케줄 seed
-- 매일 새벽 02:00에 LLM 처리 완료 archive 파일 retention 실행

INSERT INTO task_schedules (
    name, display_name, target_type, target_config,
    schedule_type, schedule_value, enabled,
    created_at, updated_at
) VALUES (
    'archive_rotation_daily',
    'Archive 파일 7일 retention (매일 02:00)',
    'archive_rotation',
    '{"max_files_per_run": 30}',
    'cron',
    '{"time": "02:00"}',
    true,
    now(),
    now()
) ON CONFLICT (name) DO NOTHING;
