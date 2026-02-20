-- 099: Notes CRUD 기능 테이블 생성
-- 생성일: 2026-02-20

-- 태그 정의 테이블
CREATE TABLE IF NOT EXISTS note_tag_defs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(50) NOT NULL UNIQUE,
    color VARCHAR(7) NOT NULL DEFAULT '#6b7280',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 메모 테이블 (활성 상태)
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title VARCHAR(200) NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    remark TEXT,
    is_pinned INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at DATETIME
);

-- 메모 아카이브 테이블
CREATE TABLE IF NOT EXISTS notes_archive (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_id INTEGER NOT NULL,
    title VARCHAR(200) NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    remark TEXT,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    archived_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 메모-태그 연결 테이블 (notes + notes_archive 공용, source로 구분)
CREATE TABLE IF NOT EXISTS note_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL REFERENCES note_tag_defs(id) ON DELETE CASCADE,
    source VARCHAR(10) NOT NULL DEFAULT 'note',
    UNIQUE(note_id, tag_id, source)
);

-- 메모 수정 이력 테이블 (다형성: source='note'|'archive', note_id는 각 테이블의 id)
CREATE TABLE IF NOT EXISTS note_histories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id INTEGER NOT NULL,
    source VARCHAR(10) NOT NULL DEFAULT 'note',
    title VARCHAR(200) NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    remark TEXT,
    changed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_notes_deleted_at ON notes(deleted_at);
CREATE INDEX IF NOT EXISTS idx_notes_is_pinned ON notes(is_pinned, created_at);
CREATE INDEX IF NOT EXISTS idx_notes_created_at ON notes(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notes_archive_archived_at ON notes_archive(archived_at DESC);
CREATE INDEX IF NOT EXISTS idx_note_tags_note_source ON note_tags(note_id, source);
CREATE INDEX IF NOT EXISTS idx_note_tags_tag_id ON note_tags(tag_id);
CREATE INDEX IF NOT EXISTS idx_note_histories_note_source ON note_histories(note_id, source);
CREATE INDEX IF NOT EXISTS idx_note_histories_changed_at ON note_histories(changed_at DESC);
