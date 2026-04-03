ALTER TABLE slides ADD COLUMN detect_engine TEXT;
ALTER TABLE slides ADD COLUMN detect_confidence REAL;
ALTER TABLE slides ADD COLUMN detect_fallback_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_slides_detect_engine ON slides(detect_engine);
