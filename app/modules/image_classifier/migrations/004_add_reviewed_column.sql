-- time_clusters 테이블에 reviewed 컬럼 추가
ALTER TABLE time_clusters ADD COLUMN reviewed BOOLEAN DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_tc_reviewed ON time_clusters(reviewed);
