-- 프록시 관리 테이블 생성
-- 작성일: 2025-12-11

-- 프록시 마스터 테이블
CREATE TABLE IF NOT EXISTS proxies (
    id INTEGER PRIMARY KEY,
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
    fail_count INTEGER DEFAULT 0,     -- 연속 실패 횟수 (성공 시 리셋)
    avg_response_time REAL,
    min_response_time REAL,
    max_response_time REAL,

    -- 우선순위 점수 (0~100, 높을수록 좋음)
    priority_score REAL DEFAULT 0,

    -- 타임스탬프
    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP,           -- 마지막으로 소스에서 확인된 시간
    last_checked_at TIMESTAMP,        -- 마지막 검증 시간
    last_success_at TIMESTAMP,        -- 마지막 성공 시간

    -- 메타
    source TEXT,                      -- 출처 (파일명, 수집기 이름 등)
    country TEXT,                     -- 국가 코드 (GeoIP)
    tags TEXT                         -- JSON 배열 ["fast", "stable", "anonymous"]
);

-- 검증 이력 테이블
CREATE TABLE IF NOT EXISTS proxy_check_history (
    id INTEGER PRIMARY KEY,
    proxy_id INTEGER NOT NULL,
    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 검증 결과
    is_valid BOOLEAN NOT NULL,
    response_time REAL,               -- 응답 시간 (초), 실패 시 NULL
    error_type TEXT,                  -- timeout/connection_refused/http_error/unknown
    error_message TEXT,               -- 상세 에러 메시지
    http_status INTEGER,              -- HTTP 응답 코드

    -- 추가 정보
    detected_ip TEXT,                 -- httpbin에서 감지된 IP
    is_anonymous BOOLEAN,             -- 원본 IP 숨김 여부

    FOREIGN KEY (proxy_id) REFERENCES proxies(id) ON DELETE CASCADE
);

-- 수집 실행 이력 테이블
CREATE TABLE IF NOT EXISTS proxy_collection_runs (
    id INTEGER PRIMARY KEY,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,

    -- 상태: running/completed/failed/cancelled
    status TEXT DEFAULT 'running',

    -- 통계
    collected_count INTEGER DEFAULT 0,   -- 수집된 프록시 수
    new_count INTEGER DEFAULT 0,         -- 신규 등록 수
    validated_count INTEGER DEFAULT 0,   -- 검증 완료 수
    valid_count INTEGER DEFAULT 0,       -- 유효 프록시 수

    -- 소스별 통계 (JSON)
    source_stats TEXT,                   -- {"ProxyScrape": 38789, "Geonode": 500, ...}

    -- 에러 정보
    error_message TEXT,

    -- 설정 정보 (JSON)
    config TEXT                          -- {"max_concurrent": 50, "timeout": 5, ...}
);

-- 인덱스: proxies 테이블
CREATE INDEX IF NOT EXISTS idx_proxies_status ON proxies(status);
CREATE INDEX IF NOT EXISTS idx_proxies_priority ON proxies(status, priority_score DESC);
CREATE INDEX IF NOT EXISTS idx_proxies_last_checked ON proxies(last_checked_at);
CREATE INDEX IF NOT EXISTS idx_proxies_protocol ON proxies(protocol);
CREATE INDEX IF NOT EXISTS idx_proxies_country ON proxies(country);

-- 인덱스: proxy_check_history 테이블
CREATE INDEX IF NOT EXISTS idx_history_proxy_date ON proxy_check_history(proxy_id, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_history_checked_at ON proxy_check_history(checked_at);

-- 인덱스: proxy_collection_runs 테이블
CREATE INDEX IF NOT EXISTS idx_collection_runs_status ON proxy_collection_runs(status);
CREATE INDEX IF NOT EXISTS idx_collection_runs_started ON proxy_collection_runs(started_at DESC);
