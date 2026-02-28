-- 108_extend_plan_records.sql
-- PlanRecord 모델 확장: category, tags, summary, superseded_by, llm_processed_at 컬럼 추가

ALTER TABLE plan_records ADD COLUMN category TEXT;
ALTER TABLE plan_records ADD COLUMN tags JSON;
ALTER TABLE plan_records ADD COLUMN summary TEXT;
ALTER TABLE plan_records ADD COLUMN superseded_by TEXT;
ALTER TABLE plan_records ADD COLUMN llm_processed_at DATETIME;

CREATE INDEX IF NOT EXISTS ix_plan_records_category ON plan_records(category);
