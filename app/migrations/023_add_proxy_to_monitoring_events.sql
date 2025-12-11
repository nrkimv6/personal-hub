-- Migration: Add proxy tracking to monitoring_events
-- Date: 2025-12-11
-- Description: 익명 모니터링 시 사용한 프록시 정보 기록

-- proxy_url 컬럼 추가 (사용한 프록시 URL)
ALTER TABLE monitoring_events ADD COLUMN proxy_url TEXT;

-- 인덱스 (프록시별 조회용)
CREATE INDEX IF NOT EXISTS ix_monitoring_events_proxy_url ON monitoring_events(proxy_url);
