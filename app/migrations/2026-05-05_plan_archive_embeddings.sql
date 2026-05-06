-- Plan Archive semantic embedding layer
-- SQLite-compatible vector storage. PostgreSQL deployments can replace vector
-- JSON with pgvector through the migration runner capability layer.

CREATE TABLE IF NOT EXISTS plan_record_chunk_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id INTEGER NOT NULL REFERENCES plan_record_chunks(id) ON DELETE CASCADE,
    plan_record_id INTEGER NOT NULL REFERENCES plan_records(id) ON DELETE CASCADE,
    provider VARCHAR(80) NOT NULL,
    model VARCHAR(160) NOT NULL,
    dimension INTEGER NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    vector JSON NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'completed',
    error_message TEXT,
    created_at DATETIME,
    updated_at DATETIME,
    CONSTRAINT uq_plan_record_chunk_embedding_config_hash
        UNIQUE (chunk_id, provider, model, dimension, content_hash)
);

CREATE INDEX IF NOT EXISTS ix_plan_record_chunk_embeddings_chunk
    ON plan_record_chunk_embeddings(chunk_id);
CREATE INDEX IF NOT EXISTS ix_plan_record_chunk_embeddings_record
    ON plan_record_chunk_embeddings(plan_record_id);
CREATE INDEX IF NOT EXISTS ix_plan_record_chunk_embeddings_config
    ON plan_record_chunk_embeddings(provider, model, dimension);
CREATE INDEX IF NOT EXISTS ix_plan_record_chunk_embeddings_status
    ON plan_record_chunk_embeddings(status);
