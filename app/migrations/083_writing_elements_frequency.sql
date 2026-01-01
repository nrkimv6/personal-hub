-- 079: Writing Elements Frequency
-- writing_elements 테이블에 빈도수 컬럼 추가

ALTER TABLE writing_elements ADD COLUMN frequency INTEGER DEFAULT NULL;
ALTER TABLE writing_elements ADD COLUMN source_keyword_id INTEGER REFERENCES keyword_stats(id);

CREATE INDEX IF NOT EXISTS idx_writing_elements_frequency ON writing_elements(frequency);
CREATE INDEX IF NOT EXISTS idx_writing_elements_source_keyword_id ON writing_elements(source_keyword_id);
