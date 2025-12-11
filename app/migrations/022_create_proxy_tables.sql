-- Migration: Create proxy tables
-- Date: 2025-12-11
-- Description: 프록시 관리를 위한 테이블 생성
-- Note: 이 마이그레이션은 별도 DB 파일에 적용됩니다 (D:/work/project/tools/shared/data/proxies.db)

-- 1. proxies 테이블 - 프록시 마스터
CREATE TABLE IF NOT EXISTS proxies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    protocol TEXT NOT NULL,           -- http/https/socks5
    host TEXT NOT NULL,
    port INTEGER NOT NULL,
    username TEXT,
    password TEXT,

    -- 상태: pending/active/inactive/blacklisted
    status TEXT DEFAULT 'pending',

    -- 통계
    total_checks INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,     -- 연속 실패 횟수
    avg_response_time REAL,
    min_response_time REAL,
    max_response_time REAL,

    -- 우선순위 점수 (0~100)
    priority_score REAL DEFAULT 0,

    -- 타임스탬프
    first_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen_at DATETIME,
    last_checked_at DATETIME,
    last_success_at DATETIME,

    -- 메타
    source TEXT,
    country TEXT,
    tags TEXT                         -- JSON 배열
);

CREATE INDEX IF NOT EXISTS idx_proxies_status ON proxies(status);
CREATE INDEX IF NOT EXISTS idx_proxies_priority ON proxies(priority_score DESC);
CREATE INDEX IF NOT EXISTS idx_proxies_protocol ON proxies(protocol);


-- 2. proxy_check_history 테이블 - 검증 이력
CREATE TABLE IF NOT EXISTS proxy_check_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proxy_id INTEGER NOT NULL,
    checked_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- 검증 결과
    is_valid BOOLEAN NOT NULL,
    response_time REAL,               -- 응답 시간 (초)
    error_type TEXT,                  -- timeout/connection_refused/http_error/unknown
    error_message TEXT,
    http_status INTEGER,

    -- 추가 정보
    detected_ip TEXT,
    is_anonymous BOOLEAN,

    FOREIGN KEY (proxy_id) REFERENCES proxies(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_proxy_history_proxy_id ON proxy_check_history(proxy_id);
CREATE INDEX IF NOT EXISTS idx_proxy_history_checked ON proxy_check_history(checked_at DESC);


-- 3. proxy_collection_runs 테이블 - 수집 실행 이력
CREATE TABLE IF NOT EXISTS proxy_collection_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME,

    -- 상태: running/completed/failed/cancelled
    status TEXT DEFAULT 'running',

    -- 통계
    collected_count INTEGER DEFAULT 0,
    new_count INTEGER DEFAULT 0,
    validated_count INTEGER DEFAULT 0,
    valid_count INTEGER DEFAULT 0,

    -- JSON 필드
    source_stats TEXT,                -- {"ProxyScrape": 38789, ...}
    error_message TEXT,
    config TEXT                       -- {"max_concurrent": 50, ...}
);

CREATE INDEX IF NOT EXISTS idx_collection_runs_started ON proxy_collection_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_collection_runs_status ON proxy_collection_runs(status);
