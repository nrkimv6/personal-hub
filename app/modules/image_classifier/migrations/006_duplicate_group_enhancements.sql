-- Migration 006: duplicate_groups 테이블 개선
-- resolution_type 컬럼 추가
-- status에 'merged' 값 추가

-- SQLite에서는 ALTER TABLE로 CHECK 제약 변경 불가
-- 기존 데이터를 보존하면서 새 테이블로 교체

-- 1. 임시 테이블에 기존 데이터 복사
CREATE TABLE duplicate_groups_new AS SELECT * FROM duplicate_groups;

-- 2. 기존 테이블 삭제
DROP TABLE duplicate_groups;

-- 3. 새 스키마로 테이블 재생성
CREATE TABLE duplicate_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_hash TEXT NOT NULL UNIQUE,
    duplicate_type TEXT NOT NULL DEFAULT 'exact' CHECK(duplicate_type IN ('exact', 'near')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'resolved', 'skipped', 'merged')),
    resolution_type TEXT DEFAULT 'select_best' CHECK(resolution_type IN ('select_best', 'keep_all', 'manual')),
    member_count INTEGER DEFAULT 0,
    kept_file_id INTEGER REFERENCES file_classifications(id),
    quality_score REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. 임시 테이블에서 데이터 복원
INSERT INTO duplicate_groups (id, group_hash, duplicate_type, status, member_count, kept_file_id, quality_score, created_at, updated_at)
SELECT id, group_hash, duplicate_type, status, member_count, kept_file_id, quality_score, created_at, updated_at
FROM duplicate_groups_new;

-- 5. 임시 테이블 삭제
DROP TABLE duplicate_groups_new;
