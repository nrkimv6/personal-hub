-- Plan intent 추출 필드 추가
-- 2026-03-25: intent, trigger, scope, plan_date, applied_at

ALTER TABLE plan_records ADD COLUMN intent TEXT;
ALTER TABLE plan_records ADD COLUMN trigger VARCHAR(50);
ALTER TABLE plan_records ADD COLUMN scope TEXT;
ALTER TABLE plan_records ADD COLUMN plan_date DATE;
ALTER TABLE plan_records ADD COLUMN applied_at DATETIME;
