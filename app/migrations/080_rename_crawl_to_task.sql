-- 080_rename_crawl_to_task.sql
-- CrawlSchedule -> TaskSchedule 리네이밍

-- 테이블 이름 변경
ALTER TABLE crawl_schedules RENAME TO task_schedules;
ALTER TABLE crawl_schedule_runs RENAME TO task_schedule_runs;

-- 인덱스는 자동으로 따라감 (SQLite)
