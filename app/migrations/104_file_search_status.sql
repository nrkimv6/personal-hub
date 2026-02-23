-- Migration 104: file_search_status 캐시 테이블 생성
-- 목적: FileSearchWorker가 30초마다 Everything/ripgrep 상태를 체크하고 캐싱
--        API의 GET /status는 이 테이블에서 즉시 반환 (Session 0에서 직접 체크 불가)

CREATE TABLE IF NOT EXISTS file_search_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    everything_ok BOOLEAN NOT NULL DEFAULT 0,
    ripgrep_ok BOOLEAN NOT NULL DEFAULT 0,
    ripgrep_path TEXT,
    checked_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 단일 행 캐시 패턴 (항상 id=1 행만 유지)
INSERT OR IGNORE INTO file_search_status (id, everything_ok, ripgrep_ok, checked_at)
VALUES (1, 0, 0, datetime('now', 'localtime'));
