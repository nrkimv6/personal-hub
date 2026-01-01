-- 080: Keyword Analysis Schedule
-- 키워드 분석 스케줄 등록

INSERT OR IGNORE INTO crawl_schedules (name, display_name, target_type, schedule_type, schedule_value, enabled)
VALUES (
    'keyword_analysis_weekly',
    '키워드 분석 (주 1회)',
    'keyword_analysis',
    'cron',
    '0 4 * * 0',
    1
);
