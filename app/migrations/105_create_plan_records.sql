-- plan_records: 계획서 메타데이터 + 메모 관리
CREATE TABLE IF NOT EXISTS plan_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename_hash TEXT UNIQUE NOT NULL,  -- sha256(생성시각 + 파일명) — 안정 식별자
    file_path TEXT NOT NULL,             -- 현재 파일 경로 (캐시, 이동 시 갱신)
    project TEXT,                        -- 프로젝트명
    title TEXT,                          -- 계획서 제목
    status TEXT,                         -- 상태 (초안/구현중/구현완료/보류)
    memo TEXT,                           -- 비고란 메모 (확정)
    memo_draft TEXT,                     -- 메모 임시저장 (자동저장용)
    archived_at DATETIME,               -- 아카이브 완료 시각
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- plan_events: 계획서 이벤트 로그 (타임라인 뷰 데이터 소스)
CREATE TABLE IF NOT EXISTS plan_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_record_id INTEGER NOT NULL REFERENCES plan_records(id),
    event_type TEXT NOT NULL,            -- created, archived, status_changed, memo_updated, path_changed, missing
    detail JSON,                         -- 이벤트 상세 (예: {"from": "초안", "to": "구현중"})
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_plan_events_record ON plan_events(plan_record_id);
CREATE INDEX IF NOT EXISTS idx_plan_events_type ON plan_events(event_type);
CREATE INDEX IF NOT EXISTS idx_plan_events_created_at ON plan_events(created_at);
CREATE INDEX IF NOT EXISTS idx_plan_records_hash ON plan_records(filename_hash);
CREATE INDEX IF NOT EXISTS idx_plan_records_project ON plan_records(project);
CREATE INDEX IF NOT EXISTS idx_plan_records_status ON plan_records(status);
