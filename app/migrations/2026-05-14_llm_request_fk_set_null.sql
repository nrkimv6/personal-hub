-- Align llm_requests child references with cleanup hard-delete semantics.

ALTER TABLE generated_writings
    DROP CONSTRAINT IF EXISTS generated_writings_llm_request_id_fkey;

UPDATE generated_writings
SET llm_request_id = NULL
WHERE llm_request_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM llm_requests
      WHERE llm_requests.id = generated_writings.llm_request_id
  );

ALTER TABLE generated_writings
    ADD CONSTRAINT generated_writings_llm_request_id_fkey
    FOREIGN KEY (llm_request_id)
    REFERENCES llm_requests(id)
    ON DELETE SET NULL;

ALTER TABLE generated_reports
    DROP CONSTRAINT IF EXISTS generated_reports_llm_request_id_fkey;

UPDATE generated_reports
SET llm_request_id = NULL
WHERE llm_request_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM llm_requests
      WHERE llm_requests.id = generated_reports.llm_request_id
  );

ALTER TABLE generated_reports
    ADD CONSTRAINT generated_reports_llm_request_id_fkey
    FOREIGN KEY (llm_request_id)
    REFERENCES llm_requests(id)
    ON DELETE SET NULL;
