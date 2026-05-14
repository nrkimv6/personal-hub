-- Align llm_requests child references with cleanup hard-delete semantics.

ALTER TABLE generated_writings
    DROP CONSTRAINT IF EXISTS generated_writings_llm_request_id_fkey;

ALTER TABLE generated_writings
    ADD CONSTRAINT generated_writings_llm_request_id_fkey
    FOREIGN KEY (llm_request_id)
    REFERENCES llm_requests(id)
    ON DELETE SET NULL;

ALTER TABLE generated_reports
    DROP CONSTRAINT IF EXISTS generated_reports_llm_request_id_fkey;

ALTER TABLE generated_reports
    ADD CONSTRAINT generated_reports_llm_request_id_fkey
    FOREIGN KEY (llm_request_id)
    REFERENCES llm_requests(id)
    ON DELETE SET NULL;
