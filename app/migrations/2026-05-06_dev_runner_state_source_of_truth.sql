-- Dev Runner Postgres source-of-truth foundation.
-- Mirror-stage DDL only; live application is left to the merge-test/deploy owner.

CREATE TABLE IF NOT EXISTS dev_runner_state (
    runner_id VARCHAR(64) PRIMARY KEY,
    plan_file TEXT NOT NULL,
    project VARCHAR(100) NOT NULL DEFAULT 'monitor-page',
    status VARCHAR(50) NOT NULL,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    branch TEXT,
    worktree_path TEXT,
    exit_reason VARCHAR(100),
    merge_requested BOOLEAN NOT NULL DEFAULT FALSE,
    completed_at TIMESTAMP,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT ck_dev_runner_state_branch_required_for_merge_status
        CHECK (status NOT IN ('머지대기', '통합테스트중') OR branch IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_dev_runner_state_status
    ON dev_runner_state(status);

CREATE INDEX IF NOT EXISTS idx_dev_runner_state_started_at
    ON dev_runner_state(started_at);

CREATE TABLE IF NOT EXISTS dev_runner_merge_request (
    id BIGSERIAL PRIMARY KEY,
    runner_id VARCHAR(64) NOT NULL REFERENCES dev_runner_state(runner_id) ON DELETE CASCADE,
    branch TEXT NOT NULL,
    worktree_path TEXT NOT NULL,
    plan_file TEXT NOT NULL,
    project VARCHAR(100) NOT NULL DEFAULT 'monitor-page',
    state VARCHAR(30) NOT NULL DEFAULT 'pending',
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    claim_token VARCHAR(128),
    claimed_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_detail TEXT
);

CREATE INDEX IF NOT EXISTS idx_merge_request_state
    ON dev_runner_merge_request(state);

CREATE INDEX IF NOT EXISTS idx_merge_request_created_at
    ON dev_runner_merge_request(created_at);

CREATE INDEX IF NOT EXISTS idx_merge_request_runner_id
    ON dev_runner_merge_request(runner_id);
