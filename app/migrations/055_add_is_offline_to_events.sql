-- 오프라인 이벤트 분리 기능
-- 작성일: 2025-12-25
-- 설명: Event 테이블에 is_offline 플래그 추가하여 온라인/오프라인 이벤트 구분

-- 1. is_offline 컬럼 추가
ALTER TABLE events ADD COLUMN is_offline BOOLEAN NOT NULL DEFAULT 0;

-- 2. 인덱스 추가 (필터 성능 최적화)
CREATE INDEX IF NOT EXISTS idx_events_is_offline ON events(is_offline);

-- 3. 기존 데이터는 모두 온라인 이벤트로 유지 (is_offline = 0)
-- (DEFAULT 0으로 자동 적용됨)
