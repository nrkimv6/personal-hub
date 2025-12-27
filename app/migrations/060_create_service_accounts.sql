-- 060_create_service_accounts.sql
-- 서비스 계정 테이블 생성 (프로필당 여러 서비스 계정 관리)
-- 2025-12-27

CREATE TABLE IF NOT EXISTS service_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 프로필 연결
    profile_id INTEGER NOT NULL,

    -- 서비스 식별
    service_type TEXT NOT NULL,              -- "naver", "instagram", "coupang"

    -- 계정 정보
    identifier TEXT,                         -- 이메일 또는 username
    password TEXT,                           -- 암호화된 비밀번호 (nullable)

    -- 상태
    is_logged_in BOOLEAN DEFAULT FALSE,      -- 로그인 상태

    -- 서비스별 추가 정보 (JSON)
    credentials TEXT,                        -- JSON: {"booking_info": {...}} for naver
    -- naver: {"booking_info": {"phone_last4": "1234", "visitor_name": "홍길동", ...}}
    -- instagram: {}
    -- coupang: {"membership": "rocket"}

    -- 메타
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (profile_id) REFERENCES browser_profiles(id) ON DELETE CASCADE,
    UNIQUE(profile_id, service_type)  -- 프로필당 서비스별 1개 계정
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_service_accounts_profile_id ON service_accounts(profile_id);
CREATE INDEX IF NOT EXISTS idx_service_accounts_service_type ON service_accounts(service_type);
CREATE INDEX IF NOT EXISTS idx_service_accounts_is_logged_in ON service_accounts(is_logged_in);
