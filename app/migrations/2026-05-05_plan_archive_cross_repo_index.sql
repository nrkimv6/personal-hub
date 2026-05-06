-- Plan Archive cross-repo file index.
-- Git remains the source of truth; these columns/tables are searchable cache.

ALTER TABLE plan_record_file_refs ADD COLUMN repo_key VARCHAR(100) NOT NULL DEFAULT 'monitor-page';
ALTER TABLE plan_record_file_refs ADD COLUMN repo_root VARCHAR(1000);
ALTER TABLE plan_record_file_refs ADD COLUMN repo_commit_sha VARCHAR(64);

CREATE INDEX IF NOT EXISTS ix_plan_record_file_refs_repo
    ON plan_record_file_refs(repo_key);

CREATE TABLE IF NOT EXISTS plan_record_repo_refs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_record_id INTEGER NOT NULL REFERENCES plan_records(id) ON DELETE CASCADE,
    repo_key VARCHAR(100) NOT NULL,
    repo_root VARCHAR(1000),
    repo_commit_sha VARCHAR(64),
    source_type VARCHAR(50) NOT NULL DEFAULT 'git_changed',
    status VARCHAR(30) NOT NULL DEFAULT 'ready',
    error_message TEXT,
    created_at DATETIME,
    updated_at DATETIME,
    CONSTRAINT uq_plan_record_repo_ref_source UNIQUE (plan_record_id, repo_key, source_type)
);

CREATE INDEX IF NOT EXISTS ix_plan_record_repo_refs_record
    ON plan_record_repo_refs(plan_record_id);
CREATE INDEX IF NOT EXISTS ix_plan_record_repo_refs_repo
    ON plan_record_repo_refs(repo_key);
CREATE INDEX IF NOT EXISTS ix_plan_record_repo_refs_status
    ON plan_record_repo_refs(status);
