-- 글쓰기 배치 테이블
-- 11개 LLM 요청 그룹(배치)을 추적하는 테이블

CREATE TABLE IF NOT EXISTS writing_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_run_id INTEGER,

    -- 진행 상태
    status TEXT DEFAULT 'pending',  -- pending/running/completed/failed
    total_count INTEGER DEFAULT 11,
    completed_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,

    -- 슬롯 컨텍스트 (JSON) - 당일 중복 방지용
    slot_context TEXT,

    -- 시간
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    started_at DATETIME,
    completed_at DATETIME,

    FOREIGN KEY (schedule_run_id) REFERENCES task_schedule_runs(id)
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_writing_batches_status ON writing_batches(status);
CREATE INDEX IF NOT EXISTS idx_writing_batches_created_at ON writing_batches(created_at);
CREATE INDEX IF NOT EXISTS idx_writing_batches_schedule_run_id ON writing_batches(schedule_run_id);
