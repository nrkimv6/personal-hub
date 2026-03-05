-- Migration 085: LLMRequest에 chat 모드 관련 컬럼 추가
-- dual-mode 계획: single-shot + chat 세션 분리

ALTER TABLE llm_requests ADD COLUMN mode VARCHAR(20) NOT NULL DEFAULT 'single';
ALTER TABLE llm_requests ADD COLUMN chat_session_id VARCHAR(100);
ALTER TABLE llm_requests ADD COLUMN stream_log_path VARCHAR(500);
