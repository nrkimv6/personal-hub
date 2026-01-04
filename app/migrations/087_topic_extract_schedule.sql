-- Topic Extract 스케줄 등록
-- 매일 05:00에 기존 소스에서 소재를 추출

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
) VALUES (
    'topic_extract_daily',
    '소재 자동 추출 (매일)',
    'topic_extract',
    '{"daily_limit": 100, "batch_size": 10, "min_interval_hours": 20}',
    'cron',
    '0 5 * * *',
    1,
    datetime('now'),
    datetime('now')
);
