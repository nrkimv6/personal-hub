CREATE TABLE IF NOT EXISTS llm_schedule_profile_policies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_id INTEGER REFERENCES task_schedules(id) ON DELETE CASCADE,
    target_type VARCHAR(100),
    engine VARCHAR(50) NOT NULL,
    profile_name VARCHAR(100) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    priority INTEGER NOT NULL DEFAULT 0,
    allowed_windows TEXT,
    quiet_windows TEXT,
    created_at DATETIME,
    updated_at DATETIME,
    CONSTRAINT uq_llm_schedule_profile_policy_schedule UNIQUE (schedule_id, engine, profile_name),
    CONSTRAINT uq_llm_schedule_profile_policy_target UNIQUE (target_type, engine, profile_name)
);

CREATE INDEX IF NOT EXISTS ix_llm_schedule_profile_policy_schedule
    ON llm_schedule_profile_policies(schedule_id);

CREATE INDEX IF NOT EXISTS ix_llm_schedule_profile_policy_target
    ON llm_schedule_profile_policies(target_type);
