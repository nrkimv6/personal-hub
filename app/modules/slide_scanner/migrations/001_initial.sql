CREATE TABLE IF NOT EXISTS slides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    result_path TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'REVIEWED', 'DONE')),

    pt_tl_x REAL,
    pt_tl_y REAL,
    pt_tr_x REAL,
    pt_tr_y REAL,
    pt_br_x REAL,
    pt_br_y REAL,
    pt_bl_x REAL,
    pt_bl_y REAL,

    captured_at TEXT,
    source_app TEXT,
    thumbnail BLOB,
    is_archived INTEGER NOT NULL DEFAULT 0,

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_slides_status ON slides(status);
CREATE INDEX IF NOT EXISTS idx_slides_captured_at ON slides(captured_at);
