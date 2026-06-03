-- Create personal books tables.

CREATE TABLE IF NOT EXISTS books (
    id SERIAL PRIMARY KEY,
    isbn VARCHAR(32) NOT NULL UNIQUE,
    title VARCHAR(240) NOT NULL,
    author VARCHAR(160) NOT NULL,
    publisher VARCHAR(160) NOT NULL DEFAULT '',
    published_year INTEGER,
    price INTEGER,
    category VARCHAR(80) NOT NULL DEFAULT '',
    cover_url TEXT,
    condition VARCHAR(20) NOT NULL DEFAULT 'good',
    location VARCHAR(240) NOT NULL DEFAULT '',
    purchased_where VARCHAR(160),
    purchased_used VARCHAR(8),
    purchased_price INTEGER,
    reason TEXT,
    reread_intent INTEGER NOT NULL DEFAULT 3,
    notes TEXT,
    accessibility_library VARCHAR(10) NOT NULL DEFAULT 'check',
    accessibility_millie VARCHAR(10) NOT NULL DEFAULT 'check',
    accessibility_ebook VARCHAR(10) NOT NULL DEFAULT 'check',
    accessibility_used_buyback VARCHAR(10) NOT NULL DEFAULT 'check',
    used_buyback_price INTEGER,
    last_checked_at VARCHAR(10),
    recommendation VARCHAR(20) NOT NULL DEFAULT 'undecided',
    disposal VARCHAR(20) NOT NULL DEFAULT 'undecided',
    sell_status VARCHAR(20) NOT NULL DEFAULT 'none',
    scan_status VARCHAR(20) NOT NULL DEFAULT 'none',
    discard_status VARCHAR(20) NOT NULL DEFAULT 'none',
    scan_purpose VARCHAR(30),
    review_date VARCHAR(10),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_books_isbn ON books (isbn);
CREATE INDEX IF NOT EXISTS ix_books_disposal ON books (disposal);

CREATE TABLE IF NOT EXISTS book_highlights (
    id SERIAL PRIMARY KEY,
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    page INTEGER NOT NULL DEFAULT 0,
    quote TEXT NOT NULL,
    memo TEXT,
    tags TEXT NOT NULL DEFAULT '[]',
    importance INTEGER NOT NULL DEFAULT 3,
    photo TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_book_highlights_book_id ON book_highlights (book_id);
