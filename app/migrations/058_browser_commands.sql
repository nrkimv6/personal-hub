-- Browser Commands Table
-- API에서 워커로 브라우저 작업을 위임하기 위한 테이블
-- 2025-12-27

-- browser_commands 테이블 생성
CREATE TABLE IF NOT EXISTS browser_commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    command_type TEXT NOT NULL,  -- 'open_browser', 'naver_login', 'check_login', 'close_browser'
    account_id INTEGER NOT NULL,
    status TEXT DEFAULT 'pending',  -- 'pending', 'processing', 'completed', 'failed'
    request_data TEXT,  -- JSON
    result_data TEXT,   -- JSON
    error_message TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    started_at TEXT,
    completed_at TEXT,
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

-- 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_browser_commands_status ON browser_commands(status);
CREATE INDEX IF NOT EXISTS idx_browser_commands_account ON browser_commands(account_id);
CREATE INDEX IF NOT EXISTS idx_browser_commands_created_at ON browser_commands(created_at);

-- worker_status 테이블에 브라우저 상태 컬럼 추가
-- (ALTER TABLE은 이미 존재하면 무시)
-- 이 컬럼들은 monitor_worker.py에서 동적으로 추가됨
