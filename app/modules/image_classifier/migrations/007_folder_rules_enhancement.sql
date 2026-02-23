-- Migration 007: 태그 폴더 규칙 + 카테고리 다중 규칙 테이블
-- Phase 6: 카테고리/태그 폴더 규칙 설정 강화

-- 태그 테이블에 폴더 규칙 컬럼 추가
ALTER TABLE tags ADD COLUMN folder_template TEXT;
ALTER TABLE tags ADD COLUMN folder_action TEXT DEFAULT 'move' CHECK (folder_action IN ('move', 'copy', 'link'));

-- 카테고리 다중 폴더 규칙 테이블 생성
CREATE TABLE IF NOT EXISTS category_folder_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    condition_type TEXT CHECK (condition_type IN ('extension', 'file_size', 'date_range') OR condition_type IS NULL),
    condition_value TEXT,
    folder_template TEXT NOT NULL,
    priority INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_category_folder_rules_category_id ON category_folder_rules(category_id);
