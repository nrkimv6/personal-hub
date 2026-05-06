-- SQLite legacy migration for local data/monitor.db.
--
-- PostgreSQL production must not execute this SQLite AUTOINCREMENT DDL directly.
-- The same table/index contract is created dialect-safely from
-- app.core.database.init_extra_tables(), using SERIAL PRIMARY KEY on PG and
-- INTEGER PRIMARY KEY AUTOINCREMENT on SQLite.

CREATE TABLE IF NOT EXISTS llm_request_profile_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL,
    engine VARCHAR(50) NOT NULL,
    profile_name VARCHAR(100) NOT NULL,
    claimed_at DATETIME NOT NULL,
    released_at DATETIME,
    stop_reason VARCHAR(100),
    FOREIGN KEY(request_id) REFERENCES llm_requests(id) ON DELETE CASCADE,
    CONSTRAINT uq_llm_profile_claim_request UNIQUE (request_id)
);

CREATE INDEX IF NOT EXISTS ix_llm_profile_claim_profile
    ON llm_request_profile_claims(engine, profile_name);

CREATE TABLE IF NOT EXISTS llm_profile_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL,
    engine VARCHAR(50) NOT NULL,
    profile_name VARCHAR(100) NOT NULL,
    selected_at DATETIME NOT NULL,
    released_at DATETIME,
    stop_reason VARCHAR(100),
    error_summary TEXT,
    FOREIGN KEY(request_id) REFERENCES llm_requests(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_llm_profile_assignment_profile
    ON llm_profile_assignments(engine, profile_name, selected_at);
