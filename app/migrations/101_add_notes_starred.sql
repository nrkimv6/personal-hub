-- Migration 101: notes 테이블에 is_starred 컬럼 추가
ALTER TABLE notes ADD COLUMN is_starred INTEGER NOT NULL DEFAULT 0;
