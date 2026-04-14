-- 116: plan_records 테이블에 claude_session_id 컬럼 추가
-- dev-runner executor_service.py가 발급한 UUID를 CLI 실행 시작 전 저장한다

ALTER TABLE plan_records ADD COLUMN claude_session_id VARCHAR(36);
