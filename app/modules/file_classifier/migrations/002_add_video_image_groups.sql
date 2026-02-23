-- ===== fc_files file_group CHECK 제약 확장 =====
-- SQLite는 CHECK 제약 직접 변경 불가 → 테이블 재생성 방식

-- 1. 새 테이블 생성 (video, image 추가된 CHECK 포함)
CREATE TABLE IF NOT EXISTS fc_files_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL UNIQUE,
    file_name TEXT NOT NULL,
    extension TEXT,
    file_size INTEGER,
    file_modified_at DATETIME,
    file_hash TEXT,

    file_group TEXT NOT NULL
        CHECK(file_group IN ('music','video','image','archive','document','installer','game','misc')),

    metadata_json TEXT,

    rule_category_id INTEGER REFERENCES fc_categories(id),
    llm_category_id INTEGER REFERENCES fc_categories(id),
    final_category_id INTEGER REFERENCES fc_categories(id),
    llm_confidence REAL,
    llm_reasoning TEXT,

    status TEXT DEFAULT 'pending'
        CHECK(status IN ('pending','metadata_extracted','rule_classified',
                         'llm_classified','approved','moved','error','skipped')),

    suggested_path TEXT,
    moved_path TEXT,

    is_deletable BOOLEAN DEFAULT FALSE,
    delete_reason TEXT,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    classified_at DATETIME,
    moved_at DATETIME
);

-- 2. 기존 데이터 복사
INSERT OR IGNORE INTO fc_files_new
SELECT * FROM fc_files;

-- 3. 기존 테이블 삭제
DROP TABLE IF EXISTS fc_files;

-- 4. 새 테이블 이름 변경
ALTER TABLE fc_files_new RENAME TO fc_files;

-- 5. 인덱스 재생성
CREATE INDEX IF NOT EXISTS idx_fcf_status ON fc_files(status);
CREATE INDEX IF NOT EXISTS idx_fcf_group ON fc_files(file_group);
CREATE INDEX IF NOT EXISTS idx_fcf_ext ON fc_files(extension);
CREATE INDEX IF NOT EXISTS idx_fcf_category ON fc_files(final_category_id);
