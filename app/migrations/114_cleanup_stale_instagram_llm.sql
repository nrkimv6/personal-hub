-- fix: Instagram LLM 분석 미동작 — PostgreSQL 마이그레이션 후 stale caller_id 정리
-- SQLite 시절 caller_id(> 5971)를 가진 요청들을 failed 처리하여 워커 무한 루프 방지 및 데이터 무결성 확보

UPDATE llm_requests 
SET status='failed', 
    error_message='stale_caller_id_after_pg_migration', 
    processed_at=NOW() 
WHERE caller_type='instagram' 
  AND status IN ('pending', 'completed', 'processing') 
  AND CAST(caller_id AS INTEGER) > (SELECT COALESCE(MAX(id), 0) FROM instagram_posts);
