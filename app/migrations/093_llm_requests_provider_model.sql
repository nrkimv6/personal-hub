-- llm_requests 테이블에 Provider 및 Model 선택 컬럼 추가

-- provider 컬럼 추가 (어떤 LLM Provider를 사용할지: claude, gemini 등)
ALTER TABLE llm_requests ADD COLUMN provider VARCHAR(20) DEFAULT 'claude';

-- model 컬럼 추가 (구체적인 모델 이름, 빈 문자열이면 Provider 기본 모델 사용)
ALTER TABLE llm_requests ADD COLUMN model VARCHAR(100) DEFAULT '';

-- 인덱스 추가 (provider별 요청 조회 최적화)
CREATE INDEX IF NOT EXISTS idx_llm_requests_provider ON llm_requests(provider);
