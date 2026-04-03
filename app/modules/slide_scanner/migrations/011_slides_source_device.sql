ALTER TABLE slides ADD COLUMN source_device_id TEXT;

CREATE INDEX IF NOT EXISTS idx_slides_source_device_id
ON slides(source_device_id);

