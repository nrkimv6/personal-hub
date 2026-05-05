-- Plan Archive retrieval index MVP
-- SQLite-compatible DDL. PostgreSQL deployments should add tsvector/GIN on
-- plan_record_chunks.text through the migration runner capability layer.

CREATE TABLE IF NOT EXISTS plan_record_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_record_id INTEGER NOT NULL REFERENCES plan_records(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    section_type VARCHAR(50) NOT NULL DEFAULT 'body',
    heading VARCHAR(500),
    text TEXT NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    token_estimate INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME,
    updated_at DATETIME,
    CONSTRAINT uq_plan_record_chunk_index UNIQUE (plan_record_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS ix_plan_record_chunks_record
    ON plan_record_chunks(plan_record_id);
CREATE INDEX IF NOT EXISTS ix_plan_record_chunks_section
    ON plan_record_chunks(section_type);
CREATE INDEX IF NOT EXISTS ix_plan_record_chunks_hash
    ON plan_record_chunks(content_hash);

CREATE TABLE IF NOT EXISTS plan_record_file_refs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_record_id INTEGER NOT NULL REFERENCES plan_records(id) ON DELETE CASCADE,
    chunk_id INTEGER REFERENCES plan_record_chunks(id) ON DELETE SET NULL,
    source_type VARCHAR(50) NOT NULL,
    path VARCHAR(1000) NOT NULL,
    module VARCHAR(200),
    change_type VARCHAR(20),
    commit_sha VARCHAR(64),
    commit_date DATETIME,
    lines_added INTEGER,
    lines_deleted INTEGER,
    evidence TEXT,
    exists_at_index BOOLEAN NOT NULL DEFAULT 0,
    first_seen_at DATETIME,
    last_seen_at DATETIME,
    created_at DATETIME,
    updated_at DATETIME,
    CONSTRAINT uq_plan_record_file_ref_source UNIQUE (plan_record_id, source_type, path, commit_sha)
);

CREATE INDEX IF NOT EXISTS ix_plan_record_file_refs_record
    ON plan_record_file_refs(plan_record_id);
CREATE INDEX IF NOT EXISTS ix_plan_record_file_refs_path
    ON plan_record_file_refs(path);
CREATE INDEX IF NOT EXISTS ix_plan_record_file_refs_source
    ON plan_record_file_refs(source_type);
CREATE INDEX IF NOT EXISTS ix_plan_record_file_refs_module
    ON plan_record_file_refs(module);
CREATE INDEX IF NOT EXISTS ix_plan_record_file_refs_seen
    ON plan_record_file_refs(first_seen_at, last_seen_at);

CREATE TABLE IF NOT EXISTS plan_record_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_plan_record_id INTEGER NOT NULL REFERENCES plan_records(id) ON DELETE CASCADE,
    target_plan_record_id INTEGER NOT NULL REFERENCES plan_records(id) ON DELETE CASCADE,
    relation_type VARCHAR(50) NOT NULL,
    score INTEGER NOT NULL DEFAULT 0,
    evidence JSON,
    created_at DATETIME,
    updated_at DATETIME,
    CONSTRAINT uq_plan_record_relation UNIQUE (source_plan_record_id, target_plan_record_id, relation_type)
);

CREATE INDEX IF NOT EXISTS ix_plan_record_relations_source
    ON plan_record_relations(source_plan_record_id);
CREATE INDEX IF NOT EXISTS ix_plan_record_relations_target
    ON plan_record_relations(target_plan_record_id);
CREATE INDEX IF NOT EXISTS ix_plan_record_relations_type
    ON plan_record_relations(relation_type);

CREATE TABLE IF NOT EXISTS plan_record_search_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_record_id INTEGER REFERENCES plan_records(id) ON DELETE SET NULL,
    run_type VARCHAR(50) NOT NULL DEFAULT 'index',
    status VARCHAR(30) NOT NULL DEFAULT 'pending',
    dry_run BOOLEAN NOT NULL DEFAULT 1,
    force BOOLEAN NOT NULL DEFAULT 0,
    indexed_count INTEGER NOT NULL DEFAULT 0,
    skipped_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    detail JSON,
    error_message TEXT,
    started_at DATETIME,
    finished_at DATETIME
);

CREATE INDEX IF NOT EXISTS ix_plan_record_search_runs_record
    ON plan_record_search_runs(plan_record_id);
CREATE INDEX IF NOT EXISTS ix_plan_record_search_runs_status
    ON plan_record_search_runs(status);
CREATE INDEX IF NOT EXISTS ix_plan_record_search_runs_started
    ON plan_record_search_runs(started_at);

-- SQLite FTS5 capability adapter may create this table at runtime:
-- CREATE VIRTUAL TABLE plan_record_chunks_fts
--   USING fts5(text, heading, content='plan_record_chunks', content_rowid='id');
-- PostgreSQL equivalent: generated tsvector or expression GIN index over
-- coalesce(heading, '') || ' ' || text, selected by runtime dialect.
