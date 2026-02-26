-- LLM Worker Quota Pause 상태 컬럼 추가
-- quota 에러 발생 시 provider별 일시중지 상태를 DB에 저장

ALTER TABLE llm_worker_status ADD COLUMN quota_paused_provider TEXT;
ALTER TABLE llm_worker_status ADD COLUMN quota_paused_until DATETIME;
ALTER TABLE llm_worker_status ADD COLUMN quota_pause_reason TEXT;
