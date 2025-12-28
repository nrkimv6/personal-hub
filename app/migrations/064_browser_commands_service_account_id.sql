-- 064_browser_commands_service_account_id.sql
-- browser_commands 테이블에 service_account_id 컬럼 추가
-- 2025-12-28

ALTER TABLE browser_commands ADD COLUMN service_account_id INTEGER REFERENCES service_accounts(id) ON DELETE SET NULL;
