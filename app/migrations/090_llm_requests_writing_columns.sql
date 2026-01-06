-- llm_requests 테이블에 글쓰기 관련 컬럼 추가

-- writing_batch_id 컬럼 추가
ALTER TABLE llm_requests ADD COLUMN writing_batch_id INTEGER;

-- writing_metadata 컬럼 추가 (JSON: task_type, source_ids, selected_elements 등)
ALTER TABLE llm_requests ADD COLUMN writing_metadata TEXT;

-- 인덱스 추가
CREATE INDEX IF NOT EXISTS idx_llm_requests_writing_batch_id ON llm_requests(writing_batch_id);
