-- Migration 103: file_search_requests 테이블 생성
-- 목적: API(Session 0) → Redis 큐 → FileSearchWorker(유저 세션) 비동기 파일 검색 요청 추적

CREATE TABLE IF NOT EXISTS file_search_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id TEXT NOT NULL UNIQUE,          -- UUID
    status TEXT NOT NULL DEFAULT 'pending',   -- pending/queued/processing/completed/failed
    request_json TEXT NOT NULL,               -- SearchRequest 직렬화
    result_json TEXT,                         -- SearchResponse 직렬화
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    completed_at TEXT,
    search_time_ms INTEGER
);

CREATE INDEX IF NOT EXISTS idx_fsr_search_id ON file_search_requests(search_id);
CREATE INDEX IF NOT EXISTS idx_fsr_status ON file_search_requests(status);
CREATE INDEX IF NOT EXISTS idx_fsr_created_at ON file_search_requests(created_at);
