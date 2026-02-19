-- 작업 진행 추적 테이블
-- 스캔, 분류, pHash, CLIP, 중복탐지 등 모든 장기 작업의 진행 상태를 DB에 저장
CREATE TABLE IF NOT EXISTS task_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type TEXT NOT NULL,                          -- scan, classify, phash, clip, duplicate, thumbnail, metadata, ai_classify
    status TEXT NOT NULL DEFAULT 'pending',           -- pending, running, paused, completed, failed
    total_items INTEGER DEFAULT 0,
    processed_items INTEGER DEFAULT 0,
    current_item TEXT,                                -- 현재 처리 중인 경로/ID
    started_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT,
    metadata TEXT                                     -- JSON 추가 정보
);

CREATE INDEX IF NOT EXISTS idx_task_progress_type_status ON task_progress(task_type, status);
