-- Migration 005: mapped_by CHECK 제약 확장
-- sibling_propagated, child_propagated 값 추가
-- 기존: user/ai_suggested/inherited
-- 추가: sibling_propagated (형제 전파), child_propagated (부모 전파)

-- SQLite에서는 CHECK 제약을 직접 ALTER TABLE로 변경할 수 없음
-- 기존 데이터를 보존하면서 새 테이블로 교체하는 방식 사용

-- 1. 임시 테이블에 기존 데이터 복사
CREATE TABLE folder_mappings_new AS SELECT * FROM folder_mappings;

-- 2. 기존 테이블 삭제
DROP TABLE folder_mappings;

-- 3. 새 CHECK 제약과 함께 테이블 재생성
CREATE TABLE folder_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_path TEXT NOT NULL UNIQUE,
    category_id INTEGER REFERENCES categories(id),
    mapped_by TEXT CHECK(mapped_by IN (
        'user',
        'ai_suggested',
        'inherited',
        'sibling_propagated',
        'child_propagated'
    )),
    parent_mapping_id INTEGER REFERENCES folder_mappings(id),
    confidence REAL,
    file_count INTEGER DEFAULT 0,
    folder_status TEXT DEFAULT 'unknown' CHECK(folder_status IN (
        'clear', 'unclear', 'flat', 'nested', 'unknown'
    )),
    is_mixed BOOLEAN DEFAULT FALSE,
    last_scanned_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. 임시 테이블에서 데이터 복원
INSERT INTO folder_mappings SELECT * FROM folder_mappings_new;

-- 5. 임시 테이블 삭제
DROP TABLE folder_mappings_new;
