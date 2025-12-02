-- Migration: Add multi-profile support (Account model)
-- Date: 2025-12-03
-- Description:
--   - Add accounts table for managing multiple browser profiles
--   - Add account_id foreign key to biz_items table
--   - Create default account

-- ============================================================
-- 1. Create accounts table
-- ============================================================

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR NOT NULL UNIQUE,              -- 계정명 (예: "메인계정")
    email VARCHAR,                             -- 네이버 이메일 (선택)
    profile_dir VARCHAR NOT NULL UNIQUE,       -- 프로필 디렉토리명
    is_active BOOLEAN NOT NULL DEFAULT 1,      -- 활성화 여부
    is_logged_in BOOLEAN NOT NULL DEFAULT 0,   -- 로그인 상태
    description TEXT,                          -- 계정 설명
    last_used_at DATETIME,                     -- 마지막 사용 시간
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 2. Create indexes for accounts table
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_accounts_name ON accounts(name);
CREATE INDEX IF NOT EXISTS idx_accounts_profile_dir ON accounts(profile_dir);
CREATE INDEX IF NOT EXISTS idx_accounts_is_active ON accounts(is_active);

-- ============================================================
-- 3. Insert default account
-- ============================================================

INSERT OR IGNORE INTO accounts (id, name, profile_dir, is_active, is_logged_in, description)
VALUES (1, '기본계정', 'default', 1, 0, '시스템 기본 계정');

-- ============================================================
-- 4. Add account_id column to biz_items table (if not exists)
-- ============================================================

-- SQLite doesn't support "IF NOT EXISTS" for ALTER TABLE ADD COLUMN
-- We need to check if the column exists first using a different approach

-- Check and add account_id column (this will fail silently if column exists)
-- Note: In SQLite, we can't easily check column existence in pure SQL
-- The migration script will handle this by trying to add the column
-- and catching any errors if it already exists

-- Add account_id column
-- This may fail if column already exists, which is expected
ALTER TABLE biz_items ADD COLUMN account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL;

-- ============================================================
-- 5. Create index for biz_items.account_id
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_biz_items_account_id ON biz_items(account_id);

-- ============================================================
-- 6. Optional: Set existing items to use default account
-- ============================================================

-- Uncomment the following line if you want to assign all existing items to the default account
-- UPDATE biz_items SET account_id = 1 WHERE account_id IS NULL;

-- ============================================================
-- Migration complete
-- ============================================================

-- To verify the migration:
-- SELECT * FROM accounts;
-- PRAGMA table_info(biz_items);
