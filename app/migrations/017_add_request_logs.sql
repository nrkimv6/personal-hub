-- 017: request_logs 테이블 추가
-- 모니터링 요청/응답 로그를 저장하기 위한 테이블

CREATE TABLE IF NOT EXISTS request_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    url VARCHAR(500),
    label VARCHAR(100),
    date VARCHAR(50),
    times VARCHAR,
    category VARCHAR(50),
    service_type VARCHAR(50),
    response_hash VARCHAR(32),
    is_valid BOOLEAN DEFAULT 1,
    is_full BOOLEAN DEFAULT 0,
    is_available BOOLEAN DEFAULT 1,
    error_message VARCHAR(500),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 조회 성능을 위한 인덱스
CREATE INDEX IF NOT EXISTS idx_request_logs_url ON request_logs(url);
CREATE INDEX IF NOT EXISTS idx_request_logs_date ON request_logs(date);
CREATE INDEX IF NOT EXISTS idx_request_logs_request_time ON request_logs(request_time);
