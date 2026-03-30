-- 오염 데이터 정리: pytest 임시경로 레코드 삭제
-- 생성: 2026-03-30
-- 목적: plan_records 테이블에서 pytest/AppData/Temp 경로 레코드 제거 및 고아 이벤트 정리

-- 1. pytest 임시경로 레코드 삭제
DELETE FROM plan_records
WHERE file_path LIKE '%pytest%'
   OR file_path LIKE '%AppData%Local%Temp%'
   OR file_path LIKE '%/tmp/%'
   OR file_path LIKE '%\\tmp\\%';

-- 2. 고아 이벤트 정리 (plan_records에 없는 record 참조)
DELETE FROM plan_events
WHERE plan_record_id NOT IN (SELECT id FROM plan_records);

-- 3. status 보정: archive 경로인데 status NULL인 것
UPDATE plan_records
SET status = 'archived'
WHERE (file_path LIKE '%/archive/%' OR file_path LIKE '%\\archive\\%')
  AND status IS NULL;

-- 4. status 보정: plan 경로인데 status NULL인 것
UPDATE plan_records
SET status = 'planned'
WHERE (file_path LIKE '%/plan/%' OR file_path LIKE '%\\plan\\%')
  AND status IS NULL
  AND (file_path NOT LIKE '%/archive/%' AND file_path NOT LIKE '%\\archive\\%');
