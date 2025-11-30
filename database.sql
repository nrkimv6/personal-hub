CREATE TABLE monitor_targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    base_url TEXT NOT NULL,
    label TEXT NOT NULL,
    date TEXT NOT NULL,
    times TEXT NOT NULL,
    category TEXT NOT NULL,
    service_type TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    interval REAL,
    custom_interval BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_enabled BOOLEAN DEFAULT TRUE,
    run_status TEXT DEFAULT 'idle',
    last_error TEXT,
    error_count INTEGER DEFAULT 0,
    -- 예약 관련 필드 (신규)
    auto_booking_enabled BOOLEAN DEFAULT FALSE,
    max_bookings INTEGER DEFAULT 1,
    booking_count INTEGER DEFAULT 0,
    time_range TEXT,
    last_booking_time DATETIME,
    booking_options TEXT
)
CREATE TABLE notification_settings ( id INTEGER NOT NULL, enable_telegram BOOLEAN, enable_desktop BOOLEAN, notify_states VARCHAR, created_at DATETIME, updated_at DATETIME, PRIMARY KEY (id) )
CREATE TABLE request_logs ( id INTEGER PRIMARY KEY AUTOINCREMENT, request_time DATETIME DEFAULT CURRENT_TIMESTAMP, url VARCHAR(500) NOT NULL, label VARCHAR(100) NOT NULL, date VARCHAR(50), -- 모니터링 날짜 times TEXT, -- 모니터링 시간대 (JSON 문자열) category VARCHAR(50), service_type VARCHAR(50), response_hash VARCHAR(32), -- 응답 내용의 해시값 is_valid BOOLEAN DEFAULT TRUE, -- 응답이 유효한지 여부 is_full BOOLEAN DEFAULT FALSE, -- 예약 마감 여부 is_available BOOLEAN DEFAULT TRUE, -- 페이지 이용 가능 여부 error_message VARCHAR(500), created_at DATETIME DEFAULT CURRENT_TIMESTAMP )
CREATE TABLE sqlite_sequence(name,seq);

-- 예약 이력 테이블 (신규)
CREATE TABLE booking_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id INTEGER REFERENCES monitor_targets(id),
    url TEXT NOT NULL,
    tag TEXT NOT NULL,
    slot_datetime TEXT NOT NULL,
    slot_info TEXT,
    success BOOLEAN DEFAULT FALSE,
    error_message TEXT,
    business_id TEXT,
    item_id TEXT,
    category TEXT,
    booking_method TEXT DEFAULT 'parallel',
    dry_run BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    booking_started_at DATETIME,
    booking_completed_at DATETIME
);

-- 사업자별 옵션 설정 테이블 (신규)
CREATE TABLE business_options (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id TEXT NOT NULL UNIQUE,
    business_name TEXT,
    option_config JSON,
    auto_fill_config JSON,
    is_active BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 모니터링 로그 테이블 (신규)
CREATE TABLE monitoring_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id INTEGER REFERENCES monitor_targets(id),
    url TEXT NOT NULL,
    tag TEXT NOT NULL,
    status TEXT NOT NULL,
    available_slots_count INTEGER DEFAULT 0,
    available_slots JSON,
    data_hash TEXT,
    hash_changed BOOLEAN DEFAULT FALSE,
    api_response JSON,
    error_message TEXT,
    response_time_ms REAL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_request_logs_category ON request_logs(category)
CREATE INDEX idx_request_logs_created_at ON request_logs(created_at)
CREATE INDEX idx_request_logs_date ON request_logs(date)
CREATE INDEX idx_request_logs_service_type ON request_logs(service_type)
CREATE INDEX idx_request_logs_url ON request_logs(url);
CREATE INDEX ix_notification_settings_id ON notification_settings (id);

-- 예약 이력 인덱스
CREATE INDEX idx_booking_history_target_id ON booking_history(target_id);
CREATE INDEX idx_booking_history_tag ON booking_history(tag);
CREATE INDEX idx_booking_history_created_at ON booking_history(created_at);
CREATE INDEX idx_booking_history_success ON booking_history(success);

-- 사업자 옵션 인덱스
CREATE INDEX idx_business_options_business_id ON business_options(business_id);

-- 모니터링 로그 인덱스
CREATE INDEX idx_monitoring_logs_target_id ON monitoring_logs(target_id);
CREATE INDEX idx_monitoring_logs_tag ON monitoring_logs(tag);
CREATE INDEX idx_monitoring_logs_status ON monitoring_logs(status);
CREATE INDEX idx_monitoring_logs_created_at ON monitoring_logs(created_at)