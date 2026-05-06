-- Migration 119: plan_records.file_delete_after
-- LLM 분석 성공 후 archive 파일 working-copy 삭제 예정 시각.

ALTER TABLE plan_records
    ADD COLUMN IF NOT EXISTS file_delete_after TIMESTAMP NULL;

CREATE INDEX IF NOT EXISTS ix_plan_records_file_delete_after
    ON plan_records(file_delete_after);
