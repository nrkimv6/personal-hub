-- Rollback: 2026-05-06_plan_archive_llm_request_dedup_and_failure_category.sql

DROP INDEX IF EXISTS uq_llm_requests_active_dedup;
DROP INDEX IF EXISTS ix_llm_requests_caller_type_status_requested;
DROP INDEX IF EXISTS ix_llm_requests_caller_type_caller_id_status;
DROP INDEX IF EXISTS ix_llm_requests_provider_model_status;
DROP INDEX IF EXISTS ix_llm_requests_failure_category_status;
DROP INDEX IF EXISTS ix_plan_records_archived_at_llm_processed;

ALTER TABLE llm_requests DROP COLUMN IF EXISTS failure_category;
ALTER TABLE llm_requests DROP COLUMN IF EXISTS dedupe_key;
