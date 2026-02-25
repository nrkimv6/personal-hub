-- 기존 아카이브 레코드에 status='archived' 일괄 업데이트
-- archived_at이 설정되어 있지만 status가 'archived'가 아닌 레코드를 수정
UPDATE plan_records
SET status = 'archived',
    updated_at = datetime('now')
WHERE archived_at IS NOT NULL
  AND (status IS NULL OR status != 'archived');
