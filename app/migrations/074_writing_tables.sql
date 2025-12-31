-- 074: Writing Tables
-- 글쓰기 소스 및 생성된 글 테이블

-- 글쓰기 소스 테이블
CREATE TABLE IF NOT EXISTS writing_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    category VARCHAR(50),
    source_info VARCHAR(200),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 생성된 글 테이블
CREATE TABLE IF NOT EXISTS generated_writings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type VARCHAR(20) NOT NULL,
    prompt_used TEXT,
    source_ids VARCHAR(100),
    content TEXT NOT NULL,
    raw_response TEXT,
    rating INTEGER,
    schedule_run_id INTEGER REFERENCES crawl_schedule_runs(id) ON DELETE SET NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    deleted_at DATETIME
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_generated_writings_created_at ON generated_writings(created_at);
CREATE INDEX IF NOT EXISTS idx_generated_writings_task_type ON generated_writings(task_type);
CREATE INDEX IF NOT EXISTS idx_generated_writings_rating ON generated_writings(rating);
CREATE INDEX IF NOT EXISTS idx_generated_writings_deleted_at ON generated_writings(deleted_at);
CREATE INDEX IF NOT EXISTS idx_generated_writings_schedule_run_id ON generated_writings(schedule_run_id);
