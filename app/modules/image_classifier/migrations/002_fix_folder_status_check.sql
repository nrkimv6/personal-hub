-- ===================================================================
-- folder_status CHECK 제약 수정
-- 생성일: 2026-02-13
-- 문제: DEFAULT 'unknown'인데 CHECK에 'unknown' 없음 → INSERT 실패
-- 해결: CHECK 제약에 'unknown' 추가
-- ===================================================================

-- SQLite는 ALTER TABLE로 CHECK 제약 수정 불가
-- 해결책: 임시 테이블 생성 → 데이터 복사 → 원본 삭제 → 이름 변경

-- 1. 수정된 스키마로 임시 테이블 생성
CREATE TABLE folder_mappings_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_path TEXT NOT NULL UNIQUE,
    category_id INTEGER REFERENCES categories(id),
    is_mixed BOOLEAN DEFAULT FALSE,
    file_count INTEGER,
    folder_status TEXT DEFAULT 'unknown'
        CHECK(folder_status IN ('unknown','clear','unclear','flat','nested')),
    mapped_by TEXT DEFAULT 'user'
        CHECK(mapped_by IN ('user','ai_suggested','inherited')),
    parent_mapping_id INTEGER REFERENCES folder_mappings(id),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 2. 기존 데이터 복사
INSERT INTO folder_mappings_new
    (id, folder_path, category_id, is_mixed, file_count, folder_status, mapped_by, parent_mapping_id, created_at)
SELECT
    id, folder_path, category_id, is_mixed, file_count, folder_status, mapped_by, parent_mapping_id, created_at
FROM folder_mappings;

-- 3. 원본 테이블 삭제
DROP TABLE folder_mappings;

-- 4. 임시 테이블 이름 변경
ALTER TABLE folder_mappings_new RENAME TO folder_mappings;

-- 5. 인덱스 재생성 (필요 시)
-- CREATE INDEX IF NOT EXISTS idx_folder_status ON folder_mappings(folder_status);
-- CREATE INDEX IF NOT EXISTS idx_folder_path ON folder_mappings(folder_path);
