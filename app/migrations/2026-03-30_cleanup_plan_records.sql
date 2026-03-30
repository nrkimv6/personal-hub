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

-- 5. 비-plan 파일 레코드 삭제 (YYYY-MM-DD 패턴이 아닌 파일명)
-- SQLite는 REGEXP 미지원 → 제외 파일 목록 직접 열거
-- 패턴: 파일명이 숫자 4개-숫자 2개-숫자 2개로 시작하지 않는 것
DELETE FROM plan_records
WHERE (
    -- 길이가 10 미만이거나 날짜 패턴(YYYY-MM-DD) 아닌 것
    length(file_path) - length(replace(file_path, '/', '')) = 0  -- 경로 구분자 없는 경우 포함
    OR
    -- 파일명이 알려진 문서 파일인 경우
    file_path LIKE '%/CLAUDE.md'
    OR file_path LIKE '%\\CLAUDE.md'
    OR file_path LIKE '%/CHANGELOG.md'
    OR file_path LIKE '%\\CHANGELOG.md'
    OR file_path LIKE '%/README.md'
    OR file_path LIKE '%\\README.md'
    OR file_path LIKE '%/TODO.md'
    OR file_path LIKE '%\\TODO.md'
    OR file_path LIKE '%/MANUAL_TASKS.md'
    OR file_path LIKE '%\\MANUAL_TASKS.md'
    OR file_path LIKE '%/DONE.md'
    OR file_path LIKE '%\\DONE.md'
    OR file_path LIKE '%/REQUIREMENTS.md'
    OR file_path LIKE '%\\REQUIREMENTS.md'
)
AND archived_at IS NULL;
