-- 059_create_browser_profiles.sql
-- 브라우저 프로필 테이블 생성 (기존 accounts 테이블 대체)
-- 2025-12-27

CREATE TABLE IF NOT EXISTS browser_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 프로필 식별
    name TEXT NOT NULL,                      -- 프로필명 ("메인", "서브1")
    profile_dir TEXT NOT NULL UNIQUE,        -- 브라우저 프로필 디렉토리 ("default", "profile_1")

    -- 상태
    is_active BOOLEAN DEFAULT TRUE,          -- 활성화 여부

    -- 메타
    description TEXT,                        -- 설명
    last_used_at TIMESTAMP,                  -- 마지막 사용 시간
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 인덱스
CREATE UNIQUE INDEX IF NOT EXISTS idx_browser_profiles_profile_dir ON browser_profiles(profile_dir);
CREATE INDEX IF NOT EXISTS idx_browser_profiles_is_active ON browser_profiles(is_active);
