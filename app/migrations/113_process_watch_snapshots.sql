-- process-watch 스냅샷/감사 로그 테이블
CREATE TABLE IF NOT EXISTS process_watch_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TEXT NOT NULL,
    pid INTEGER NOT NULL,
    ppid INTEGER,
    parent_pid INTEGER,
    parent_name TEXT,
    name TEXT,
    exe TEXT,
    cmdline TEXT,
    cmdline_hash TEXT,
    create_time REAL,
    memory_mb REAL,
    is_orphan INTEGER DEFAULT 0,
    scope TEXT DEFAULT 'external',
    captured_by TEXT DEFAULT 'periodic'
);

CREATE TABLE IF NOT EXISTS process_watch_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    acted_at TEXT NOT NULL,
    action TEXT NOT NULL,
    pid INTEGER NOT NULL,
    cmdline_hash TEXT,
    reason TEXT,
    actor TEXT,
    result TEXT,
    detail TEXT
);

CREATE INDEX IF NOT EXISTS idx_pws_captured_at ON process_watch_snapshots(captured_at);
CREATE INDEX IF NOT EXISTS idx_pws_pid ON process_watch_snapshots(pid);
CREATE INDEX IF NOT EXISTS idx_pws_orphan ON process_watch_snapshots(is_orphan);
CREATE INDEX IF NOT EXISTS idx_pws_memory ON process_watch_snapshots(memory_mb);
CREATE INDEX IF NOT EXISTS idx_pws_hash ON process_watch_snapshots(cmdline_hash);

CREATE INDEX IF NOT EXISTS idx_pwa_acted_at ON process_watch_actions(acted_at);
CREATE INDEX IF NOT EXISTS idx_pwa_pid ON process_watch_actions(pid);
CREATE INDEX IF NOT EXISTS idx_pwa_hash ON process_watch_actions(cmdline_hash);
