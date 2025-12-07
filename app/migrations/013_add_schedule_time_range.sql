-- 마이그레이션: monitor_schedules에 time_range 컬럼 추가
-- 날짜: 2025-12-07
-- 목적: 일정 레벨에서 시간 범위를 관리하도록 변경 (기존 biz_items.time_range 대신)

-- 1. time_range 컬럼 추가
ALTER TABLE monitor_schedules ADD COLUMN time_range TEXT;

-- 2. 기존 times 필드에서 범위 형식 데이터를 time_range로 이전
-- times가 '["13:00-20:00"]' 형식인 경우 time_range로 이동
UPDATE monitor_schedules
SET time_range = REPLACE(REPLACE(times, '["', ''), '"]', ''),
    times = NULL
WHERE times LIKE '%-%'
  AND times LIKE '["%"]'
  AND LENGTH(REPLACE(REPLACE(times, '["', ''), '"]', '')) <= 11;

-- 3. biz_items.time_range 값을 time_range가 없는 일정에 복사 (기본값으로)
UPDATE monitor_schedules
SET time_range = (
    SELECT bi.time_range
    FROM biz_items bi
    WHERE bi.id = monitor_schedules.biz_item_id
)
WHERE monitor_schedules.time_range IS NULL;
