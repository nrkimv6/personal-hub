-- 078: Keyword Stats Extension
-- keyword_stats 테이블에 승격/불용어 관련 컬럼 추가

ALTER TABLE keyword_stats ADD COLUMN is_stopword INTEGER DEFAULT 0;
ALTER TABLE keyword_stats ADD COLUMN is_promoted INTEGER DEFAULT 0;
ALTER TABLE keyword_stats ADD COLUMN element_id INTEGER REFERENCES writing_elements(id);
ALTER TABLE keyword_stats ADD COLUMN reviewed_at DATETIME;

CREATE INDEX IF NOT EXISTS idx_keyword_stats_is_stopword ON keyword_stats(is_stopword);
CREATE INDEX IF NOT EXISTS idx_keyword_stats_is_promoted ON keyword_stats(is_promoted);
CREATE INDEX IF NOT EXISTS idx_keyword_stats_element_id ON keyword_stats(element_id);
