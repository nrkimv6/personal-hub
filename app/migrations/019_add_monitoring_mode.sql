-- 019_add_monitoring_mode.sql
-- 익명 모니터링 모드 지원을 위한 마이그레이션
-- 작성일: 2025-12-10

-- monitor_schedules 테이블에 모니터링 모드 컬럼 추가
-- 'legacy': 기존 방식 (로그인 탭으로 전체 수행)
-- 'anonymous': 익명 모드 (익명 조회 + 필요시 탭 사용)
ALTER TABLE monitor_schedules
ADD COLUMN monitoring_mode VARCHAR(20) DEFAULT 'legacy';

-- 학습된 영업시간 저장 테이블
-- 익명 모니터링 시 예약 이력이 있는 슬롯 시간을 수집하여 영업시간을 학습
CREATE TABLE IF NOT EXISTS learned_business_hours (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id TEXT NOT NULL,
    biz_item_id TEXT NOT NULL,
    slot_time TEXT NOT NULL,  -- "HH:MM" 형식
    occurrence_count INTEGER DEFAULT 1,
    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(business_id, biz_item_id, slot_time)
);

-- 인덱스 생성 (빠른 조회용)
CREATE INDEX IF NOT EXISTS idx_learned_hours_business
ON learned_business_hours(business_id, biz_item_id);
