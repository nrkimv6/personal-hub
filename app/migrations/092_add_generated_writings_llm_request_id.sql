-- 092: Add llm_request_id to generated_writings table

ALTER TABLE generated_writings ADD COLUMN llm_request_id INTEGER REFERENCES llm_requests(id);

CREATE INDEX IF NOT EXISTS idx_generated_writings_llm_request_id ON generated_writings(llm_request_id);
