-- Google Search Queue 테이블 생성
-- Google 검색 요청을 큐에 저장하여 워커에서 처리

CREATE TABLE IF NOT EXISTS google_search_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id TEXT UNIQUE NOT NULL,
    query TEXT NOT NULL,
    date_filter TEXT,
    max_pages INTEGER DEFAULT 1,
    service_account_id INTEGER,
    saved_search_id INTEGER,
    status TEXT DEFAULT 'pending',  -- pending, processing, completed, failed
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    FOREIGN KEY (service_account_id) REFERENCES service_accounts(id) ON DELETE SET NULL,
    FOREIGN KEY (saved_search_id) REFERENCES google_saved_searches(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_google_search_queue_status ON google_search_queue(status);
CREATE INDEX IF NOT EXISTS idx_google_search_queue_created_at ON google_search_queue(created_at);
