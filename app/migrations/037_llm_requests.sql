-- LLM 요청 테이블 (범용)
-- 여러 모듈에서 Claude LLM 호출 시 사용

CREATE TABLE IF NOT EXISTS llm_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 호출자 식별
    caller_type TEXT NOT NULL,              -- 'instagram', 'naver', etc.
    caller_id TEXT NOT NULL,                -- 호출자 측 ID

    -- 요청 정보
    prompt TEXT NOT NULL,
    requested_at DATETIME DEFAULT (datetime('now')),

    -- 처리 상태
    status TEXT DEFAULT 'pending' NOT NULL,  -- pending/processing/completed/failed
    processed_at DATETIME,

    -- 결과
    result TEXT,                             -- JSON 응답
    raw_response TEXT,                       -- Claude 원본 응답
    error_message TEXT,
    retry_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_llm_requests_status ON llm_requests(status);
CREATE INDEX IF NOT EXISTS idx_llm_requests_caller ON llm_requests(caller_type, caller_id);
CREATE INDEX IF NOT EXISTS idx_llm_requests_requested_at ON llm_requests(requested_at);

-- LLM 워커 상태 테이블
CREATE TABLE IF NOT EXISTS llm_worker_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id TEXT UNIQUE NOT NULL,
    pid INTEGER,
    started_at DATETIME DEFAULT (datetime('now')),
    last_heartbeat DATETIME,
    current_state TEXT DEFAULT 'idle',       -- idle/processing/stopped
    current_request_id INTEGER REFERENCES llm_requests(id) ON DELETE SET NULL,
    is_alive INTEGER DEFAULT 1,
    processed_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_llm_worker_status_alive ON llm_worker_status(is_alive);
