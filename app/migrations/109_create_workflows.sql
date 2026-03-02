-- 109_create_workflows.sql
-- Workflow 테이블 생성: dev-runner 브랜치/계획서/runner 상태 영속화
-- 2026-03-03

CREATE TABLE IF NOT EXISTS workflows (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        TEXT    NOT NULL UNIQUE,
    plan_file   TEXT,
    branch      TEXT,
    runner_id   TEXT,
    status      TEXT    NOT NULL DEFAULT 'planned',
    engine      TEXT,
    error_message TEXT,
    commit_hash TEXT,
    worktree_path TEXT,
    created_at  TEXT,
    started_at  TEXT,
    merged_at   TEXT,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS ix_workflows_status     ON workflows (status);
CREATE INDEX IF NOT EXISTS ix_workflows_slug       ON workflows (slug);
CREATE INDEX IF NOT EXISTS ix_workflows_created_at ON workflows (created_at);
