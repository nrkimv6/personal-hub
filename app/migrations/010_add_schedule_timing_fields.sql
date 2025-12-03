-- Migration: Add timing fields to monitor_schedules
-- Date: 2025-12-04
-- Purpose: 마지막 체크 시간과 다음 실행 시간을 저장하여 대기열에서 표시

-- 1. last_check_time 컬럼 추가 (마지막 모니터링 실행 시간)
ALTER TABLE monitor_schedules ADD COLUMN last_check_time DATETIME;

-- 2. next_run_time 컬럼 추가 (다음 모니터링 예정 시간)
ALTER TABLE monitor_schedules ADD COLUMN next_run_time DATETIME;

-- 3. 인덱스 추가 (대기열 조회 성능 향상)
CREATE INDEX IF NOT EXISTS idx_monitor_schedules_next_run ON monitor_schedules(next_run_time);
