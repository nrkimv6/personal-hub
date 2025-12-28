-- 063_add_biz_items_service_account_id.sql
-- biz_items 테이블에 service_account_id 컬럼 추가 (061에서 누락됨)
-- 2025-12-28

-- biz_items 테이블에 service_account_id 컬럼 추가
ALTER TABLE biz_items ADD COLUMN service_account_id INTEGER REFERENCES service_accounts(id) ON DELETE SET NULL;
