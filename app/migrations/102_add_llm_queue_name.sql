-- Migration 102: llm_requests에 queue_name 컬럼 추가
-- 목적: 멀티큐 워커 설계 — utility(기존 자동화) / system(시스템/개발) 큐 분리

ALTER TABLE llm_requests ADD COLUMN queue_name VARCHAR(30) DEFAULT 'utility' NOT NULL;

CREATE INDEX IF NOT EXISTS idx_llm_requests_queue_pending
    ON llm_requests(queue_name, status, requested_at);
