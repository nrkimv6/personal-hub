-- Migration: Move account_id from biz_items to monitor_schedules
-- Date: 2025-12-03
-- Purpose: 계정을 스케줄 단위로 연결하여 같은 상품에 여러 계정이 모니터링 가능하게 함

-- 1. monitor_schedules에 account_id 컬럼 추가
ALTER TABLE monitor_schedules ADD COLUMN account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL;

-- 2. 기존 biz_items의 account_id를 해당 schedules로 복사
UPDATE monitor_schedules
SET account_id = (SELECT account_id FROM biz_items WHERE biz_items.id = monitor_schedules.biz_item_id);

-- 3. 인덱스 추가
CREATE INDEX IF NOT EXISTS idx_monitor_schedules_account ON monitor_schedules(account_id);

-- Note: biz_items.account_id 컬럼은 SQLite 제한으로 제거하지 않음 (코드에서만 사용 중단)
