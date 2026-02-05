-- 096_browser_commands_nullable_account_id.sql
-- browser_commands 테이블의 account_id NOT NULL 제약 제거
-- account_id는 레거시 컬럼으로 더 이상 사용되지 않음 (service_account_id로 대체됨)
-- SQLite는 ALTER COLUMN을 지원하지 않으므로 테이블 재생성 필요
-- 2026-02-05

-- 1. 새 테이블 생성 (account_id를 nullable로 변경)
CREATE TABLE IF NOT EXISTS browser_commands_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    command_type TEXT NOT NULL,
    account_id INTEGER,  -- nullable로 변경 (레거시, service_account_id로 대체)
    status TEXT DEFAULT 'pending',
    request_data TEXT,
    result_data TEXT,
    error_message TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    started_at TEXT,
    completed_at TEXT,
    service_account_id INTEGER REFERENCES service_accounts(id) ON DELETE SET NULL
);

-- 2. 기존 데이터 복사
INSERT INTO browser_commands_new (id, command_type, account_id, status, request_data, result_data, error_message, created_at, started_at, completed_at, service_account_id)
SELECT id, command_type, account_id, status, request_data, result_data, error_message, created_at, started_at, completed_at, service_account_id
FROM browser_commands;

-- 3. 기존 테이블 삭제
DROP TABLE browser_commands;

-- 4. 새 테이블 이름 변경
ALTER TABLE browser_commands_new RENAME TO browser_commands;

-- 5. 인덱스 재생성
CREATE INDEX IF NOT EXISTS idx_browser_commands_status ON browser_commands(status);
CREATE INDEX IF NOT EXISTS idx_browser_commands_account ON browser_commands(account_id);
CREATE INDEX IF NOT EXISTS idx_browser_commands_created_at ON browser_commands(created_at);
CREATE INDEX IF NOT EXISTS idx_browser_commands_service_account ON browser_commands(service_account_id);
