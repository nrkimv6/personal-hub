-- LLM Request Management: 요청자 추적 및 관리 기능
-- 2025-12-22

-- 요청자 정보 컬럼 추가
ALTER TABLE llm_requests ADD COLUMN requested_by TEXT DEFAULT 'unknown';
ALTER TABLE llm_requests ADD COLUMN request_source TEXT;

-- Soft delete 지원
ALTER TABLE llm_requests ADD COLUMN deleted_at DATETIME;

-- 인덱스 추가
CREATE INDEX IF NOT EXISTS idx_llm_requests_requested_by ON llm_requests(requested_by);
CREATE INDEX IF NOT EXISTS idx_llm_requests_deleted ON llm_requests(deleted_at);
