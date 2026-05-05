-- plan_execution_claims 테이블 생성 (2026-05-05)
-- 계획서 실행점유 registry — runner/session/pid/heartbeat 단일 source of truth
-- > 상태: vocabulary와 분리된 claim 상태(queued/active/released/stale)를 관리한다.

CREATE TABLE IF NOT EXISTS plan_execution_claims (
    id SERIAL PRIMARY KEY,
    claim_id VARCHAR(36) NOT NULL UNIQUE,
    plan_record_id INTEGER REFERENCES plan_records(id) ON DELETE SET NULL,
    plan_path TEXT NOT NULL,
    state VARCHAR(20) NOT NULL DEFAULT 'queued',
    engine VARCHAR(50),
    session_id VARCHAR(36),
    runner_id VARCHAR(36),
    pid INTEGER,
    host VARCHAR(255),
    branch TEXT,
    worktree_path TEXT,
    claimed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    heartbeat_at TIMESTAMP,
    lease_expires_at TIMESTAMP,
    released_at TIMESTAMP,
    queue_after TIMESTAMP,
    claim_metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_plan_execution_claims_plan_path_state ON plan_execution_claims(plan_path, state);
CREATE INDEX IF NOT EXISTS ix_plan_execution_claims_state ON plan_execution_claims(state);
CREATE INDEX IF NOT EXISTS ix_plan_execution_claims_runner_id ON plan_execution_claims(runner_id);
