-- 에러 로그 테이블 생성
-- 시스템 전반의 에러를 중앙 집중 저장

CREATE TABLE IF NOT EXISTS error_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 분류
    source VARCHAR(50) NOT NULL,      -- api, worker, naver, instagram, writing
    severity VARCHAR(20) NOT NULL,    -- critical, error, warning
    error_type VARCHAR(100) NOT NULL, -- 예외 클래스명

    -- 상세 정보
    message TEXT NOT NULL,
    traceback TEXT,
    context JSON,                     -- 추가 컨텍스트

    -- 해결 상태
    resolved BOOLEAN NOT NULL DEFAULT 0,
    resolved_at DATETIME,
    resolved_by VARCHAR(100),
    notes TEXT
);

-- 인덱스 생성
CREATE INDEX IF NOT EXISTS ix_error_logs_created_at ON error_logs(created_at);
CREATE INDEX IF NOT EXISTS ix_error_logs_source ON error_logs(source);
CREATE INDEX IF NOT EXISTS ix_error_logs_severity ON error_logs(severity);
CREATE INDEX IF NOT EXISTS ix_error_logs_error_type ON error_logs(error_type);
CREATE INDEX IF NOT EXISTS ix_error_logs_resolved ON error_logs(resolved);
CREATE INDEX IF NOT EXISTS ix_error_logs_source_severity ON error_logs(source, severity);
CREATE INDEX IF NOT EXISTS ix_error_logs_created_resolved ON error_logs(created_at, resolved);
