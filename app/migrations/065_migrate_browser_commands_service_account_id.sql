-- 065_migrate_browser_commands_service_account_id.sql
-- browser_commands 테이블의 account_id(profile_id) 데이터를 service_account_id로 마이그레이션
-- 2025-12-29

-- 기존 account_id(profile_id)를 기반으로 service_account_id 채우기
-- request_data에 service_account_id가 있으면 그 값 사용
UPDATE browser_commands
SET service_account_id = CAST(json_extract(request_data, '$.service_account_id') AS INTEGER)
WHERE service_account_id IS NULL
  AND request_data IS NOT NULL
  AND json_extract(request_data, '$.service_account_id') IS NOT NULL;

-- request_data에 service_account_id가 없는 경우, account_id(profile_id)로 service_accounts 조회
UPDATE browser_commands
SET service_account_id = (
    SELECT sa.id FROM service_accounts sa
    WHERE sa.profile_id = browser_commands.account_id
    LIMIT 1
)
WHERE service_account_id IS NULL
  AND account_id IS NOT NULL;
