-- 079: Writing Source 자동 수집 스케줄
-- 2026-01-01

-- 매일 새벽 5시 자동 수집 스케줄 생성
INSERT OR IGNORE INTO crawl_schedules (
    name,
    display_name,
    target_type,
    target_config,
    schedule_type,
    schedule_value,
    enabled,
    next_run_at,
    created_at,
    updated_at
) VALUES (
    'writing_source_collect_daily',
    '글쓰기 소재 자동 수집 (매일 05:00)',
    'writing_source_collect',
    '{"collect_rss": true, "collect_wikisource": true, "collect_search": false, "daily_runs": 1, "min_interval_hours": 20, "time_windows": [{"start_hour": 5, "end_hour": 6}], "rss_min_length": 300, "rss_max_length": 3000, "wiki_min_length": 200, "wiki_max_length": 10000}',
    'time_window',
    '05:00',
    1,
    datetime('now', '+1 day', 'start of day', '+5 hours'),
    datetime('now'),
    datetime('now')
);
