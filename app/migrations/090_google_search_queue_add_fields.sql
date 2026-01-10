-- Google 검색 큐에 결과 개수 및 스케줄 ID 필드 추가
-- 워커 실행 이력 통합을 위한 마이그레이션

-- 결과 개수 필드 추가
ALTER TABLE google_search_queue ADD COLUMN result_count INTEGER DEFAULT 0;

-- 스케줄 ID 필드 추가 (스케줄 실행 시 기록용)
ALTER TABLE google_search_queue ADD COLUMN schedule_id INTEGER REFERENCES task_schedules(id) ON DELETE SET NULL;

-- 인덱스 추가 (이력 조회 성능 향상)
CREATE INDEX IF NOT EXISTS idx_google_search_queue_schedule_id ON google_search_queue(schedule_id);
CREATE INDEX IF NOT EXISTS idx_google_search_queue_status ON google_search_queue(status);
CREATE INDEX IF NOT EXISTS idx_google_search_queue_created_at ON google_search_queue(created_at);
