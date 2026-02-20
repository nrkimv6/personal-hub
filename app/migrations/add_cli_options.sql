-- llm_requests에 cli_options 컬럼 추가
-- CLI 옵션을 JSON으로 유연하게 전달 (image_classify 등)
ALTER TABLE llm_requests ADD COLUMN cli_options TEXT;
