-- Instagram LLM Classification Tables
-- 2025-12-21

-- LLM 분류 요청 테이블
CREATE TABLE IF NOT EXISTS instagram_llm_classification_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 대상 게시물
    post_id INTEGER NOT NULL REFERENCES instagram_posts(id) ON DELETE CASCADE,

    -- 요청 정보
    requested_at DATETIME DEFAULT (datetime('now')),
    requested_by TEXT DEFAULT 'auto',  -- 'auto', 'manual'
    trigger_tag TEXT,  -- LLM 분류를 트리거한 태그 (예: 'event')

    -- 처리 상태
    status TEXT DEFAULT 'pending' NOT NULL,  -- 'pending', 'processing', 'completed', 'failed'
    processed_at DATETIME,

    -- LLM 결과 (JSON)
    llm_result TEXT,  -- {"organizer": "...", "event_url": "...", "event_date": "...", "event_time": "...", "details": "..."}
    confidence_score REAL,  -- LLM 자신감 점수 (0.0 ~ 1.0)

    -- 에러 정보
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,

    -- 프롬프트/응답 로깅 (디버깅용)
    prompt_used TEXT,
    raw_response TEXT
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_llm_requests_status ON instagram_llm_classification_requests(status);
CREATE INDEX IF NOT EXISTS idx_llm_requests_post_id ON instagram_llm_classification_requests(post_id);
CREATE INDEX IF NOT EXISTS idx_llm_requests_requested_at ON instagram_llm_classification_requests(requested_at);

-- LLM 워커 상태 테이블
CREATE TABLE IF NOT EXISTS instagram_llm_worker_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id TEXT UNIQUE NOT NULL,
    pid INTEGER,
    started_at DATETIME NOT NULL,
    last_heartbeat DATETIME NOT NULL,
    current_state TEXT DEFAULT 'idle',  -- 'idle', 'processing', 'stopped'
    current_request_id INTEGER REFERENCES instagram_llm_classification_requests(id) ON DELETE SET NULL,
    is_alive BOOLEAN DEFAULT 1,
    processed_count INTEGER DEFAULT 0,  -- 처리한 총 요청 수
    error_count INTEGER DEFAULT 0       -- 에러 발생 횟수
);

CREATE INDEX IF NOT EXISTS idx_llm_worker_alive ON instagram_llm_worker_status(is_alive);
