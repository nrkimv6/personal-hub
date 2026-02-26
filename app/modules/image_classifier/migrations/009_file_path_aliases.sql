-- 삭제된 중복 이미지의 원본 경로 저장 (카테고리 판정 정보 보존)
CREATE TABLE IF NOT EXISTS file_path_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER REFERENCES file_classifications(id),
    alias_path TEXT NOT NULL,
    source TEXT DEFAULT 'duplicate_merge',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(file_id, alias_path)
);
CREATE INDEX IF NOT EXISTS idx_fpa_file_id ON file_path_aliases(file_id);
