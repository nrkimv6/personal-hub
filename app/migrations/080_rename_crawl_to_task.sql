-- 080_rename_crawl_to_task.sql
-- CrawlSchedule -> TaskSchedule 리네이밍
--
-- 주의: 이 마이그레이션은 crawl_schedules 테이블이 존재할 때만 실행하세요.
-- SQLite는 IF EXISTS를 지원하지 않으므로, 수동으로 테이블 존재 여부를 확인해야 합니다.
--
-- 테이블 존재 여부 확인:
--   SELECT name FROM sqlite_master WHERE type='table' AND name='crawl_schedules';

-- 테이블 이름 변경
ALTER TABLE crawl_schedules RENAME TO task_schedules;
ALTER TABLE crawl_schedule_runs RENAME TO task_schedule_runs;

-- 인덱스는 자동으로 따라감 (SQLite)

-- 참고: FK 참조 변경은 SQLite에서 직접 지원되지 않음
-- instagram_worker_status.current_run_id와 generated_writings.schedule_run_id가
-- 이제 task_schedule_runs를 참조하도록 모델이 업데이트됨
-- 기존 데이터의 FK는 테이블 이름이 변경되어도 동작함 (같은 레코드 참조)
