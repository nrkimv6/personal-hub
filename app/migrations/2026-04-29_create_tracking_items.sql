CREATE TABLE IF NOT EXISTS tracking_items (
    id SERIAL PRIMARY KEY,
    title VARCHAR NOT NULL,
    description TEXT,
    start_at TIMESTAMP,
    due_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_tracking_items_start_at ON tracking_items(start_at);
CREATE INDEX IF NOT EXISTS ix_tracking_items_due_at ON tracking_items(due_at);
CREATE INDEX IF NOT EXISTS ix_tracking_items_completed_at ON tracking_items(completed_at);
