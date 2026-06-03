-- Store provider buyback quotes by external condition grade.

CREATE TABLE IF NOT EXISTS book_buyback_quotes (
    id SERIAL PRIMARY KEY,
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    provider VARCHAR(40) NOT NULL DEFAULT 'aladin',
    grade VARCHAR(20) NOT NULL,
    price INTEGER,
    currency VARCHAR(8) NOT NULL DEFAULT 'KRW',
    availability VARCHAR(20) NOT NULL DEFAULT 'yes',
    raw_status VARCHAR(40) NOT NULL DEFAULT 'ok',
    message TEXT,
    checked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_book_buyback_quote_grade UNIQUE (book_id, provider, grade)
);

CREATE INDEX IF NOT EXISTS ix_book_buyback_quotes_book_id ON book_buyback_quotes (book_id);
CREATE INDEX IF NOT EXISTS ix_book_buyback_quotes_provider_grade ON book_buyback_quotes (provider, grade);
