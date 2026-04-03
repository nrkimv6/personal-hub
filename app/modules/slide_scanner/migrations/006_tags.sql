ALTER TABLE slides ADD COLUMN tag TEXT;

CREATE INDEX IF NOT EXISTS idx_slides_tag
ON slides(tag);
