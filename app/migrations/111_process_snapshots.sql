-- 프로세스 스냅샷 이력 테이블
CREATE TABLE IF NOT EXISTS process_snapshots (
    id INTEGER PRIMARY KEY,
    captured_at TEXT NOT NULL,
    pid INTEGER NOT NULL,
    ppid INTEGER,
    name TEXT,
    exe TEXT,
    role TEXT,
    memory_mb REAL,
    is_orphan INTEGER DEFAULT 0,
    action_taken TEXT
);

CREATE INDEX IF NOT EXISTS idx_ps_captured ON process_snapshots(captured_at);
CREATE INDEX IF NOT EXISTS idx_ps_orphan ON process_snapshots(is_orphan) WHERE is_orphan = 1;
