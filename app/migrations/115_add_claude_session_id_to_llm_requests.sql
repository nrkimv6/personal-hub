-- 115: llm_requests 테이블에 claude_session_id 컬럼 추가
-- Claude CLI stdout JSON의 session_id를 저장해 JSONL 파일과 DB 요청을 연결한다

ALTER TABLE llm_requests ADD COLUMN IF NOT EXISTS claude_session_id VARCHAR(36);

CREATE INDEX IF NOT EXISTS idx_llm_requests_claude_session_id
  ON llm_requests(claude_session_id)
  WHERE claude_session_id IS NOT NULL;
