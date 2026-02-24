-- Migration 008: duplicate_groups status 인덱스 추가
-- folder-analysis 쿼리 성능 개선 (WHERE status = 'pending' 풀 테이블 스캔 방지)

CREATE INDEX IF NOT EXISTS idx_dg_status ON duplicate_groups(status);
