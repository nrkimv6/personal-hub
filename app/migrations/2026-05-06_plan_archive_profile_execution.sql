CREATE TABLE IF NOT EXISTS plan_archive_execution_jobs (
    id SERIAL PRIMARY KEY,
    plan_record_id INTEGER NOT NULL REFERENCES plan_records(id) ON DELETE CASCADE,
    trigger_source VARCHAR(100) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'pending',
    selected_profiles JSONB,
    profile_count INTEGER NOT NULL DEFAULT 0,
    latest_request_id INTEGER REFERENCES llm_requests(id) ON DELETE SET NULL,
    next_available_at TIMESTAMP,
    error_message TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    queued_at TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_plan_archive_execution_jobs_record
    ON plan_archive_execution_jobs(plan_record_id);
CREATE INDEX IF NOT EXISTS ix_plan_archive_execution_jobs_status
    ON plan_archive_execution_jobs(status);
CREATE INDEX IF NOT EXISTS ix_plan_archive_execution_jobs_trigger
    ON plan_archive_execution_jobs(trigger_source);
CREATE INDEX IF NOT EXISTS ix_plan_archive_execution_jobs_latest_request
    ON plan_archive_execution_jobs(latest_request_id);

CREATE TABLE IF NOT EXISTS plan_archive_execution_attempts (
    id SERIAL PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES plan_archive_execution_jobs(id) ON DELETE CASCADE,
    llm_request_id INTEGER REFERENCES llm_requests(id) ON DELETE SET NULL,
    attempt_index INTEGER NOT NULL DEFAULT 1,
    status VARCHAR(30) NOT NULL DEFAULT 'queued',
    engine VARCHAR(50),
    profile_name VARCHAR(100),
    provider VARCHAR(50),
    model VARCHAR(100),
    retryable INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    requested_at TIMESTAMP,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_plan_archive_execution_attempt_request UNIQUE (llm_request_id)
);

CREATE INDEX IF NOT EXISTS ix_plan_archive_execution_attempts_job
    ON plan_archive_execution_attempts(job_id);
CREATE INDEX IF NOT EXISTS ix_plan_archive_execution_attempts_status
    ON plan_archive_execution_attempts(status);
CREATE INDEX IF NOT EXISTS ix_plan_archive_execution_attempts_request
    ON plan_archive_execution_attempts(llm_request_id);
CREATE INDEX IF NOT EXISTS ix_plan_archive_execution_attempts_profile
    ON plan_archive_execution_attempts(engine, profile_name);
