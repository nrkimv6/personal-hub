-- instagram_worker_status.current_run_id FK 변경
-- 작성일: 2025-12-31
-- 목적: instagram_crawl_runs 대신 crawl_schedule_runs 참조
--
-- SQLite는 ALTER TABLE로 FK 수정이 안되므로 테이블 재생성 필요

-- 1. 기존 테이블 백업
CREATE TABLE IF NOT EXISTS instagram_worker_status_backup AS SELECT * FROM instagram_worker_status;

-- 2. 기존 테이블 삭제
DROP TABLE IF EXISTS instagram_worker_status;

-- 3. 새 테이블 생성 (FK를 crawl_schedule_runs로 변경)
CREATE TABLE instagram_worker_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id VARCHAR(36) NOT NULL UNIQUE,
    pid INTEGER,
    started_at DATETIME NOT NULL,
    last_heartbeat DATETIME NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    current_state VARCHAR(20) DEFAULT 'idle',
    current_account VARCHAR(100),
    current_run_id INTEGER REFERENCES crawl_schedule_runs(id) ON DELETE SET NULL,
    is_alive BOOLEAN DEFAULT 1
);

-- 4. 데이터 복원 (current_run_id는 NULL로 - 레거시 run_id는 더 이상 유효하지 않음)
INSERT INTO instagram_worker_status (
    id, worker_id, pid, started_at, last_heartbeat, created_at,
    current_state, current_account, current_run_id, is_alive
)
SELECT
    id, worker_id, pid, started_at, last_heartbeat, created_at,
    current_state, current_account, NULL, is_alive
FROM instagram_worker_status_backup;

-- 5. 백업 테이블 삭제
DROP TABLE IF EXISTS instagram_worker_status_backup;

-- 6. 인덱스 재생성
CREATE INDEX IF NOT EXISTS idx_instagram_worker_status_worker_id ON instagram_worker_status(worker_id);
CREATE INDEX IF NOT EXISTS idx_instagram_worker_status_heartbeat ON instagram_worker_status(last_heartbeat);
CREATE INDEX IF NOT EXISTS idx_instagram_worker_status_alive ON instagram_worker_status(is_alive);
