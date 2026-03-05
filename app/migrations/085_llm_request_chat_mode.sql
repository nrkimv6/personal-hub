-- Migration 085: LLMRequest chat mode columns
-- LLM Worker 듀얼 모드 (Single-shot + Chat) 지원을 위한 컬럼 추가

ALTER TABLE llm_requests ADD COLUMN mode VARCHAR(20) NOT NULL DEFAULT 'single';
ALTER TABLE llm_requests ADD COLUMN chat_session_id VARCHAR(100);
ALTER TABLE llm_requests ADD COLUMN stream_log_path VARCHAR(500);
