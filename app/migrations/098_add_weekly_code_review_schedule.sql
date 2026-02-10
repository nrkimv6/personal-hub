-- 098_add_weekly_code_review_schedule.sql
-- Add weekly_code_review schedule to task_schedules table
-- This schedule runs every Sunday at 02:00-03:00 to generate LLM-based weekly code review reports

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
    'weekly_code_review',
    '주간 코드 리뷰',
    'report',
    '{"report_type": "weekly_code_review", "min_interval_hours": 168, "period": "weekly"}',
    'time_window',
    '{"time_windows": [["02:00", "03:00"]], "daily_runs": 1}',
    1,
    datetime('now'),
    datetime('now')
);
