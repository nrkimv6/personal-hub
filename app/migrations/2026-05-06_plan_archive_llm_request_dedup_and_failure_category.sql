-- Plan Archive: LLMRequest dedupe_key + failure_category + indexes
-- Phase 2A + 2B (2026-05-06)
-- Rollback: 2026-05-06_plan_archive_llm_request_dedup_and_failure_category_rollback.sql

-- 1. failure_category stored column
ALTER TABLE llm_requests
    ADD COLUMN IF NOT EXISTS failure_category VARCHAR(30) DEFAULT NULL;
-- values: timeout / quota / parse / network / other

-- 2. dedupe_key for archive duplicate queuing prevention
ALTER TABLE llm_requests
    ADD COLUMN IF NOT EXISTS dedupe_key VARCHAR(200) DEFAULT NULL;
-- archive profile-backed: 'profile:{profile_key}' or 'profile:{engine}:{profile_name}'
-- archive profile-less (codex/gpt): 'profileless'
-- non-archive callers: NULL (unconstrained)

-- 3. Partial unique index: same (caller_type, caller_id, provider, model, dedupe_key)
--    must not have two active (pending/processing) requests
CREATE UNIQUE INDEX IF NOT EXISTS uq_llm_requests_active_dedup
    ON llm_requests(caller_type, caller_id, provider, model, dedupe_key)
    WHERE status IN ('pending', 'processing') AND deleted_at IS NULL AND dedupe_key IS NOT NULL;

-- 4. Queue lookup indexes for archive operations page
CREATE INDEX IF NOT EXISTS ix_llm_requests_caller_type_status_requested
    ON llm_requests(caller_type, status, requested_at DESC);
CREATE INDEX IF NOT EXISTS ix_llm_requests_caller_type_caller_id_status
    ON llm_requests(caller_type, caller_id, status);
CREATE INDEX IF NOT EXISTS ix_llm_requests_provider_model_status
    ON llm_requests(provider, model, status);
CREATE INDEX IF NOT EXISTS ix_llm_requests_failure_category_status
    ON llm_requests(failure_category, status)
    WHERE failure_category IS NOT NULL;

-- 5. PlanRecord candidate filter indexes
CREATE INDEX IF NOT EXISTS ix_plan_records_archived_at_llm_processed
    ON plan_records(archived_at, llm_processed_at)
    WHERE archived_at IS NOT NULL;

-- Backfill dedupe_key for existing pending/processing archive requests
-- (sets 'profileless' as default for archive requests without a profile claim)
UPDATE llm_requests
SET dedupe_key = 'profileless'
WHERE caller_type = 'plan_archive_analyze'
  AND status IN ('pending', 'processing')
  AND deleted_at IS NULL
  AND dedupe_key IS NULL;
