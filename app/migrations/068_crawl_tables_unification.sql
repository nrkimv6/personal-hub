-- 크롤링 테이블 통합 마이그레이션
-- 작성일: 2025-12-29
-- 목적: Instagram 종속 구조를 범용 구조로 전환

-- 1. crawl_requests (단건 요청)
CREATE TABLE IF NOT EXISTS crawl_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 요청 정보
    url TEXT NOT NULL,
    url_type TEXT NOT NULL,  -- 'instagram', 'naver_blog', 'google_form', ...

    -- 상태 (워커 실행 시도 포함)
    status TEXT NOT NULL DEFAULT 'pending',
    -- pending: 대기중
    -- picked: 워커가 가져감
    -- processing: 크롤링 진행중
    -- completed: 완료
    -- failed: 실패

    -- 요청 출처
    requested_by TEXT DEFAULT 'manual',  -- 'manual', 'api', 'retry'
    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 처리 정보
    picked_at TIMESTAMP,
    processed_at TIMESTAMP,
    worker_id TEXT,  -- 처리한 워커 ID

    -- 결과 연결 (다형성)
    result_type TEXT,  -- 'instagram_post', 'crawled_page'
    result_id INTEGER,

    -- 에러
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,

    -- 인덱스용
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_crawl_requests_status ON crawl_requests(status);
CREATE INDEX IF NOT EXISTS idx_crawl_requests_url_type ON crawl_requests(url_type);
CREATE INDEX IF NOT EXISTS idx_crawl_requests_requested_at ON crawl_requests(requested_at);

-- 2. crawl_schedules (스케줄 설정)
CREATE TABLE IF NOT EXISTS crawl_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 스케줄 식별
    name TEXT NOT NULL UNIQUE,  -- 'instagram_feed_account_1', 'naver_blog_event'
    display_name TEXT,

    -- 대상 설정
    target_type TEXT NOT NULL,  -- 'instagram_feed', 'naver_blog', 'naver_cafe'
    target_config TEXT,  -- JSON: {"account_id": 1, "keyword": "이벤트", ...}

    -- 주기 설정
    schedule_type TEXT NOT NULL,  -- 'cron', 'interval', 'time_window'
    schedule_value TEXT,  -- '0 9,14,21 * * *', '1h', '{"times": ["09:00", "14:00", "21:00"]}'

    -- 활성화
    enabled INTEGER DEFAULT 1,

    -- 실행 상태
    last_run_at TIMESTAMP,
    next_run_at TIMESTAMP,

    -- 메타
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_crawl_schedules_enabled ON crawl_schedules(enabled);
CREATE INDEX IF NOT EXISTS idx_crawl_schedules_next_run ON crawl_schedules(next_run_at);
CREATE INDEX IF NOT EXISTS idx_crawl_schedules_target_type ON crawl_schedules(target_type);

-- 3. crawl_schedule_runs (스케줄 실행 이력)
CREATE TABLE IF NOT EXISTS crawl_schedule_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 스케줄 연결
    schedule_id INTEGER NOT NULL,

    -- 실행 정보
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,

    -- 상태
    status TEXT NOT NULL DEFAULT 'running',
    -- running, completed, failed

    -- 결과 통계
    collected_count INTEGER DEFAULT 0,
    saved_count INTEGER DEFAULT 0,

    -- 상세 정보 (선택적)
    stop_reason TEXT,  -- 'max_posts_reached', 'duplicate_stop', ...
    error_message TEXT,
    config_snapshot TEXT,  -- JSON: 실행 시점 설정

    -- 워커 정보
    worker_id TEXT,

    -- 재시도 정보
    retry_count INTEGER DEFAULT 0,
    retry_of_run_id INTEGER,

    FOREIGN KEY (schedule_id) REFERENCES crawl_schedules(id) ON DELETE CASCADE,
    FOREIGN KEY (retry_of_run_id) REFERENCES crawl_schedule_runs(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_crawl_schedule_runs_schedule ON crawl_schedule_runs(schedule_id);
CREATE INDEX IF NOT EXISTS idx_crawl_schedule_runs_started ON crawl_schedule_runs(started_at);
CREATE INDEX IF NOT EXISTS idx_crawl_schedule_runs_status ON crawl_schedule_runs(status);

-- 4. instagram_posts에 schedule_run_id 추가 (기존 crawl_run_id 대체용)
ALTER TABLE instagram_posts ADD COLUMN schedule_run_id INTEGER REFERENCES crawl_schedule_runs(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_instagram_posts_schedule_run ON instagram_posts(schedule_run_id);

-- 5. crawled_pages에 schedule_run_id 추가
ALTER TABLE crawled_pages ADD COLUMN schedule_run_id INTEGER REFERENCES crawl_schedule_runs(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_crawled_pages_schedule_run ON crawled_pages(schedule_run_id);
