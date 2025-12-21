-- Instagram Worker Status 테이블 생성
-- 워커 프로세스의 heartbeat 및 상태를 추적

CREATE TABLE IF NOT EXISTS instagram_worker_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id TEXT NOT NULL UNIQUE,           -- 워커 인스턴스 ID (UUID)
    pid INTEGER,                              -- 프로세스 ID
    started_at TEXT NOT NULL,                 -- 워커 시작 시간
    last_heartbeat TEXT NOT NULL,             -- 마지막 heartbeat
    current_state TEXT DEFAULT 'idle',        -- idle, crawling, processing
    current_account TEXT,                     -- 현재 처리 중인 계정
    current_run_id INTEGER,                   -- 현재 실행 중인 crawl_run_id
    is_alive INTEGER DEFAULT 1,               -- 활성 여부
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (current_run_id) REFERENCES instagram_crawl_runs(id) ON DELETE SET NULL
);

-- 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_worker_status_alive ON instagram_worker_status(is_alive);
CREATE INDEX IF NOT EXISTS idx_worker_status_heartbeat ON instagram_worker_status(last_heartbeat);
CREATE INDEX IF NOT EXISTS idx_worker_status_worker_id ON instagram_worker_status(worker_id);
