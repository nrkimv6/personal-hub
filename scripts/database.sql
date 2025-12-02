-- ============================================================
-- Monitor Page Database Schema (v2)
-- 최종 업데이트: 2025-12-03
-- 설계 문서: 2025-12-01_monitoring_restructure_design.md
-- ============================================================
--
-- 마이그레이션 히스토리:
--   - 001_add_hierarchical_tables.sql: 계층형 테이블 구조
--   - 002_migrate_targets_to_hierarchical.py: 기존 데이터 마이그레이션
--   - 003_add_graphql_detail_fields.sql: GraphQL API 상세정보 필드

-- ============================================================
-- 레거시 테이블 (v1) - 더 이상 사용하지 않음
-- ============================================================

-- 기존 모니터링 타겟 테이블 (deprecated, 참조용)
CREATE TABLE IF NOT EXISTS monitor_targets (
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
    auto_booking_enabled BOOLEAN DEFAULT FALSE,
    max_bookings INTEGER DEFAULT 1,
    booking_count INTEGER DEFAULT 0,
    time_range TEXT,
    last_booking_time DATETIME,
    booking_options TEXT
);

-- 알림 설정 테이블
CREATE TABLE IF NOT EXISTS notification_settings (
    id INTEGER NOT NULL PRIMARY KEY,
    enable_telegram BOOLEAN,
    enable_desktop BOOLEAN,
    notify_states VARCHAR,
    created_at DATETIME,
    updated_at DATETIME
);

-- 요청 로그 테이블
CREATE TABLE IF NOT EXISTS request_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    url VARCHAR(500) NOT NULL,
    label VARCHAR(100) NOT NULL,
    date VARCHAR(50),
    times TEXT,
    category VARCHAR(50),
    service_type VARCHAR(50),
    response_hash VARCHAR(32),
    is_valid BOOLEAN DEFAULT TRUE,
    is_full BOOLEAN DEFAULT FALSE,
    is_available BOOLEAN DEFAULT TRUE,
    error_message VARCHAR(500),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_request_logs_category ON request_logs(category);
CREATE INDEX IF NOT EXISTS idx_request_logs_created_at ON request_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_request_logs_date ON request_logs(date);
CREATE INDEX IF NOT EXISTS idx_request_logs_service_type ON request_logs(service_type);
CREATE INDEX IF NOT EXISTS idx_request_logs_url ON request_logs(url);
CREATE INDEX IF NOT EXISTS ix_notification_settings_id ON notification_settings (id);

-- 예약 이력 테이블
CREATE TABLE IF NOT EXISTS booking_history (
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

CREATE INDEX IF NOT EXISTS idx_booking_history_target_id ON booking_history(target_id);
CREATE INDEX IF NOT EXISTS idx_booking_history_tag ON booking_history(tag);
CREATE INDEX IF NOT EXISTS idx_booking_history_created_at ON booking_history(created_at);
CREATE INDEX IF NOT EXISTS idx_booking_history_success ON booking_history(success);

-- 사업자별 옵션 설정 테이블 (deprecated)
CREATE TABLE IF NOT EXISTS business_options (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id TEXT NOT NULL UNIQUE,
    business_name TEXT,
    option_config JSON,
    auto_fill_config JSON,
    is_active BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_business_options_business_id ON business_options(business_id);

-- 모니터링 로그 테이블
CREATE TABLE IF NOT EXISTS monitoring_logs (
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

CREATE INDEX IF NOT EXISTS idx_monitoring_logs_target_id ON monitoring_logs(target_id);
CREATE INDEX IF NOT EXISTS idx_monitoring_logs_tag ON monitoring_logs(tag);
CREATE INDEX IF NOT EXISTS idx_monitoring_logs_status ON monitoring_logs(status);
CREATE INDEX IF NOT EXISTS idx_monitoring_logs_created_at ON monitoring_logs(created_at);


-- ============================================================
-- 계층형 테이블 (v2) - 현재 활성
-- ============================================================

-- ============================================
-- 1. businesses 테이블 (업체)
-- ============================================
CREATE TABLE IF NOT EXISTS businesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 식별자
    business_id TEXT NOT NULL UNIQUE,           -- 네이버 business_id (예: "987654")
    business_type_id INTEGER,                   -- 네이버 business_type_id

    -- 기본 정보
    name TEXT NOT NULL,                         -- 업체명 (예: "전통주갤러리")
    service_type TEXT NOT NULL DEFAULT 'naver', -- 서비스 타입 (naver/coupang)
    category TEXT,                              -- 카테고리

    -- 업체 레벨 설정
    booking_options TEXT,                       -- JSON: 사업자별 예약 옵션 설정

    -- 활성화 상태 (REQ-MGT-005)
    is_enabled INTEGER DEFAULT 1,               -- 업체 단위 모니터링 활성화

    -- GraphQL API 상세정보 (REQ-DATA-004)
    place_id TEXT,                              -- 네이버 플레이스 ID
    service_name TEXT,                          -- 서비스명 (예: "전통주갤러리 명동점")
    road_address TEXT,                          -- 도로명 주소
    jibun_address TEXT,                         -- 지번 주소
    detail_address TEXT,                        -- 상세 주소
    latitude REAL,                              -- 위도
    longitude REAL,                             -- 경도
    phone TEXT,                                 -- 대표 전화번호
    api_synced_at TIMESTAMP,                    -- 마지막 API 동기화 시간

    -- 메타
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_businesses_business_id ON businesses(business_id);
CREATE INDEX IF NOT EXISTS idx_businesses_service_type ON businesses(service_type);
CREATE INDEX IF NOT EXISTS idx_businesses_latitude ON businesses(latitude);
CREATE INDEX IF NOT EXISTS idx_businesses_longitude ON businesses(longitude);
CREATE INDEX IF NOT EXISTS idx_businesses_api_synced_at ON businesses(api_synced_at);


-- ============================================
-- 2. biz_items 테이블 (아이템)
-- ============================================
CREATE TABLE IF NOT EXISTS biz_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 관계
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,

    -- 식별자
    biz_item_id TEXT NOT NULL,                  -- 네이버 biz_item_id (예: "555")

    -- 기본 정보
    name TEXT NOT NULL,                         -- 아이템명 (예: "프리미엄 시음 코스")
    base_url TEXT,                              -- 기본 URL (날짜 제외)

    -- 아이템 레벨 설정
    time_range TEXT,                            -- 예약 시간 범위 (예: "10:00-21:00")
    auto_booking_enabled INTEGER DEFAULT 0,     -- SQLite에서 BOOLEAN은 INTEGER
    max_bookings_per_schedule INTEGER DEFAULT 1, -- 일정당 최대 예약 횟수
    booking_options_override TEXT,              -- JSON: 업체 설정 오버라이드

    -- 활성화 상태 (REQ-MGT-005)
    is_enabled INTEGER DEFAULT 1,               -- 아이템 단위 모니터링 활성화

    -- GraphQL API 상세정보 (REQ-DATA-004)
    description TEXT,                           -- 상품 설명
    biz_item_type TEXT,                         -- 아이템 타입 (예: "BOOKING")
    biz_item_sub_type TEXT,                     -- 서브 타입 (예: "TICKET")
    booking_count_type TEXT,                    -- 예약 타입 (예: "GROUP_TICKET")
    min_booking_count INTEGER,                  -- 최소 예약 인원
    max_booking_count INTEGER,                  -- 최대 예약 인원
    start_date TEXT,                            -- 아이템 시작일
    end_date TEXT,                              -- 아이템 종료일
    extra_desc_json TEXT,                       -- JSON: 추가 설명 목록
    booking_precaution_json TEXT,               -- JSON: 예약 주의사항 목록
    api_synced_at TIMESTAMP,                    -- 마지막 API 동기화 시간

    -- 메타
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(business_id, biz_item_id)
);

CREATE INDEX IF NOT EXISTS idx_biz_items_business_id ON biz_items(business_id);
CREATE INDEX IF NOT EXISTS idx_biz_items_biz_item_id ON biz_items(biz_item_id);
CREATE INDEX IF NOT EXISTS idx_biz_items_api_synced_at ON biz_items(api_synced_at);


-- ============================================
-- 3. monitor_schedules 테이블 (모니터링 일정)
-- ============================================
CREATE TABLE IF NOT EXISTS monitor_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 관계
    biz_item_id INTEGER NOT NULL REFERENCES biz_items(id) ON DELETE CASCADE,

    -- 일정 정보
    date TEXT NOT NULL,                         -- 예약 날짜 (예: "2025-12-15")
    times TEXT,                                 -- JSON: 선택적 시간 목록 (비어있으면 전체)

    -- 상태 (REQ-MON-004)
    is_enabled INTEGER DEFAULT 1,               -- 사용자 설정: 모니터링 원함
    is_active INTEGER DEFAULT 0,                -- 시스템 상태: 실제 모니터링 중
    run_status TEXT DEFAULT 'idle',             -- idle/pending/queued/running/paused/stopped/error

    -- 에러 추적
    last_error TEXT,
    error_count INTEGER DEFAULT 0,

    -- 스케줄링
    interval REAL,                              -- 모니터링 간격 (초)
    custom_interval INTEGER DEFAULT 0,          -- 사용자 정의 간격 여부

    -- 예약 추적
    booking_count INTEGER DEFAULT 0,            -- 이 일정의 예약 성공 횟수
    last_booking_time TIMESTAMP,

    -- 메타
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(biz_item_id, date)
);

CREATE INDEX IF NOT EXISTS idx_monitor_schedules_biz_item_id ON monitor_schedules(biz_item_id);
CREATE INDEX IF NOT EXISTS idx_monitor_schedules_date ON monitor_schedules(date);
CREATE INDEX IF NOT EXISTS idx_monitor_schedules_is_enabled ON monitor_schedules(is_enabled);
CREATE INDEX IF NOT EXISTS idx_monitor_schedules_run_status ON monitor_schedules(run_status);


-- ============================================
-- 4. v2 monitor_logs 테이블 (세션별 모니터링 로그)
-- ============================================
CREATE TABLE IF NOT EXISTS monitor_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 세션 식별
    session_id TEXT NOT NULL,                   -- 모니터링 세션 ID

    -- 관계
    schedule_id INTEGER REFERENCES monitor_schedules(id) ON DELETE SET NULL,

    -- 참조 정보 (schedule 삭제 시에도 유지)
    business_id TEXT,                           -- 업체 ID
    biz_item_id TEXT,                           -- 상품 ID
    date TEXT,                                  -- 모니터링 날짜

    -- 로그 정보
    log_type TEXT NOT NULL,                     -- 로그 타입: info/warning/error/success
    message TEXT NOT NULL,                      -- 로그 메시지

    -- 슬롯 정보
    available_slots_count INTEGER DEFAULT 0,
    available_slots_json TEXT,                  -- JSON: 가용 슬롯 목록

    -- API 응답 정보
    data_hash TEXT,
    hash_changed INTEGER DEFAULT 0,
    response_time_ms REAL,

    -- 메타
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_monitor_logs_session_id ON monitor_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_monitor_logs_schedule_id ON monitor_logs(schedule_id);
CREATE INDEX IF NOT EXISTS idx_monitor_logs_log_type ON monitor_logs(log_type);
CREATE INDEX IF NOT EXISTS idx_monitor_logs_created_at ON monitor_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_monitor_logs_business_id ON monitor_logs(business_id);
