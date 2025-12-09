-- 모니터링 이벤트 상세 정보 추가
-- 2025-12-08

-- fetch 방식 (graphql_api, html_scrape)
ALTER TABLE monitoring_events ADD COLUMN fetch_method TEXT;

-- 적용된 시간 필터 (예: "10:00-21:00")
ALTER TABLE monitoring_events ADD COLUMN time_range TEXT;

-- 필터링 전 전체 슬롯 개수
ALTER TABLE monitoring_events ADD COLUMN original_slot_count INTEGER;

-- time_range 필터링 후 슬롯 개수
ALTER TABLE monitoring_events ADD COLUMN filtered_slot_count INTEGER;

-- time_range 내 슬롯이 있는지 여부 (0: 없음, 1: 있음)
ALTER TABLE monitoring_events ADD COLUMN target_time_matched INTEGER DEFAULT 0;

-- 자동 예약이 트리거되었는지 (0: 아니오, 1: 예)
ALTER TABLE monitoring_events ADD COLUMN booking_triggered INTEGER DEFAULT 0;

-- 예약 성공 여부 (NULL: 미시도, 0: 실패, 1: 성공)
ALTER TABLE monitoring_events ADD COLUMN booking_success INTEGER;
