CREATE TABLE IF NOT EXISTS dismissed_duplicates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity1_id INTEGER NOT NULL,
    entity2_id INTEGER NOT NULL,
    dismissed_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    dismissed_by TEXT,
    CONSTRAINT uq_dismissed_duplicates_pair UNIQUE (entity_type, entity1_id, entity2_id)
);

CREATE INDEX IF NOT EXISTS idx_dismissed_duplicates_lookup
    ON dismissed_duplicates(entity_type, entity1_id, entity2_id);
