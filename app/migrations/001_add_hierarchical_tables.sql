-- 모니터링 구조 개편: 계층형 테이블 추가
-- 생성일: 2025-12-01
-- 설계 문서: 2025-12-01_monitoring_restructure_design.md

-- ============================================
-- 1. businesses 테이블 (업체)
-- ============================================
CREATE TABLE IF NOT EXISTS businesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 식별자
    business_id TEXT NOT NULL UNIQUE,       -- 네이버 business_id (예: "987654")
    business_type_id INTEGER,                -- 네이버 business_type_id

    -- 기본 정보
    name TEXT NOT NULL,                      -- 업체명 (예: "전통주갤러리")
    service_type TEXT NOT NULL DEFAULT 'naver',  -- 서비스 타입 (naver/coupang)
    category TEXT,                           -- 카테고리

    -- 업체 레벨 설정
    booking_options TEXT,                    -- JSON: 사업자별 예약 옵션 설정

    -- 메타
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_businesses_business_id ON businesses(business_id);
CREATE INDEX IF NOT EXISTS idx_businesses_service_type ON businesses(service_type);

-- ============================================
-- 2. biz_items 테이블 (아이템)
-- ============================================
CREATE TABLE IF NOT EXISTS biz_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 관계
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,

    -- 식별자
    biz_item_id TEXT NOT NULL,               -- 네이버 biz_item_id (예: "555")

    -- 기본 정보
    name TEXT NOT NULL,                      -- 아이템명 (예: "프리미엄 시음 코스")
    base_url TEXT,                           -- 기본 URL (날짜 제외)

    -- 아이템 레벨 설정
    time_range TEXT,                         -- 예약 시간 범위 (예: "10:00-21:00")
    auto_booking_enabled INTEGER DEFAULT 0,  -- SQLite에서 BOOLEAN은 INTEGER
    max_bookings_per_schedule INTEGER DEFAULT 1,  -- 일정당 최대 예약 횟수
    booking_options_override TEXT,           -- JSON: 업체 설정 오버라이드

    -- 메타
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(business_id, biz_item_id)
);

CREATE INDEX IF NOT EXISTS idx_biz_items_business_id ON biz_items(business_id);
CREATE INDEX IF NOT EXISTS idx_biz_items_biz_item_id ON biz_items(biz_item_id);

-- ============================================
-- 3. monitor_schedules 테이블 (모니터링 일정)
-- ============================================
CREATE TABLE IF NOT EXISTS monitor_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 관계
    biz_item_id INTEGER NOT NULL REFERENCES biz_items(id) ON DELETE CASCADE,

    -- 일정 정보
    date TEXT NOT NULL,                      -- 예약 날짜 (예: "2025-12-15")
    times TEXT,                              -- JSON: 선택적 시간 목록 (비어있으면 전체)

    -- 상태 (REQ-MON-004)
    is_enabled INTEGER DEFAULT 1,            -- 사용자 설정: 모니터링 원함
    is_active INTEGER DEFAULT 0,             -- 시스템 상태: 실제 모니터링 중
    run_status TEXT DEFAULT 'idle',          -- idle/pending/queued/running/paused/stopped/error

    -- 에러 추적
    last_error TEXT,
    error_count INTEGER DEFAULT 0,

    -- 스케줄링
    interval REAL,                           -- 모니터링 간격 (초)
    custom_interval INTEGER DEFAULT 0,       -- 사용자 정의 간격 여부

    -- 예약 추적
    booking_count INTEGER DEFAULT 0,         -- 이 일정의 예약 성공 횟수
    last_booking_time TIMESTAMP,

    -- 메타
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_monitor_schedules_biz_item_id ON monitor_schedules(biz_item_id);
CREATE INDEX IF NOT EXISTS idx_monitor_schedules_date ON monitor_schedules(date);
CREATE INDEX IF NOT EXISTS idx_monitor_schedules_is_enabled ON monitor_schedules(is_enabled);
CREATE INDEX IF NOT EXISTS idx_monitor_schedules_run_status ON monitor_schedules(run_status);
