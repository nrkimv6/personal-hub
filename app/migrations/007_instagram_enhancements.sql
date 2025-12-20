-- Instagram 크롤러 고우선순위 기능 확장
-- 2025-12-21

-- =============================================================================
-- 1. instagram_schedule_config 테이블 확장
-- =============================================================================

-- 최소 실행 간격 (시간 단위)
ALTER TABLE instagram_schedule_config ADD COLUMN min_interval_hours INTEGER DEFAULT 2;

-- 중복 감지 중단 (연속 중복 개수)
ALTER TABLE instagram_schedule_config ADD COLUMN duplicate_stop_count INTEGER DEFAULT 5;

-- 재시도 설정
ALTER TABLE instagram_schedule_config ADD COLUMN max_retries INTEGER DEFAULT 3;
ALTER TABLE instagram_schedule_config ADD COLUMN retry_interval_minutes INTEGER DEFAULT 5;

-- =============================================================================
-- 2. instagram_crawl_runs 테이블 확장
-- =============================================================================

-- 재시도 정보
ALTER TABLE instagram_crawl_runs ADD COLUMN retry_count INTEGER DEFAULT 0;
ALTER TABLE instagram_crawl_runs ADD COLUMN retry_of_run_id INTEGER REFERENCES instagram_crawl_runs(id);

-- 실패 사유 분류
ALTER TABLE instagram_crawl_runs ADD COLUMN failure_reason TEXT;
-- 가능한 값: 'login_required', 'network_error', 'timeout', 'rate_limit', 'unknown'

-- =============================================================================
-- 3. instagram_crawl_requests 테이블 (수동 실행 큐)
-- =============================================================================

CREATE TABLE IF NOT EXISTS instagram_crawl_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 요청 정보
    account_id INTEGER NOT NULL,
    requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    requested_by TEXT DEFAULT 'manual',  -- 'manual', 'scheduler', 'retry'

    -- 처리 상태
    status TEXT DEFAULT 'pending',  -- 'pending', 'processing', 'completed', 'failed'
    processed_at DATETIME,
    crawl_run_id INTEGER,

    -- 오류 정보
    error_message TEXT,

    -- 외래 키
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
    FOREIGN KEY (crawl_run_id) REFERENCES instagram_crawl_runs(id) ON DELETE SET NULL
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_instagram_crawl_requests_status ON instagram_crawl_requests(status);
CREATE INDEX IF NOT EXISTS idx_instagram_crawl_requests_requested_at ON instagram_crawl_requests(requested_at);

-- =============================================================================
-- 4. 기존 설정 업데이트 (기본값 적용)
-- =============================================================================

UPDATE instagram_schedule_config
SET min_interval_hours = 2,
    duplicate_stop_count = 5,
    max_retries = 3,
    retry_interval_minutes = 5
WHERE min_interval_hours IS NULL;
