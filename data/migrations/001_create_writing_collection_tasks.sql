-- Migration: 001_create_writing_collection_tasks
-- Description: writing 수집 작업 비동기 처리를 위한 상태 추적 테이블
-- Date: 2026-02-23

-- task type enum
CREATE TYPE writing_collection_task_type AS ENUM (
    'feeds_collect',
    'search_queries_collect',
    'wikisource_collect'
);

-- task status enum
CREATE TYPE writing_collection_task_status AS ENUM (
    'pending',
    'running',
    'completed',
    'failed'
);

CREATE TABLE IF NOT EXISTS writing_collection_tasks (
    task_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type        writing_collection_task_type NOT NULL,
    status      writing_collection_task_status NOT NULL DEFAULT 'pending',

    -- 진행 상황 (JSON): {"collected": 12, "total": 50, "current_source": "rss_feed_url"}
    progress_json   TEXT,

    -- 결과 요약 (JSON): {"collected_count": 50, "skipped": 3, "sources": [...]}
    result_json     TEXT,

    -- 오류 메시지 (실패 시)
    error_message   TEXT,

    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMP,
    completed_at    TIMESTAMP
);

-- 상태별 조회 인덱스
CREATE INDEX IF NOT EXISTS idx_writing_collection_tasks_status
    ON writing_collection_tasks (status);

-- 생성일 기준 최신 조회 인덱스
CREATE INDEX IF NOT EXISTS idx_writing_collection_tasks_created_at
    ON writing_collection_tasks (created_at DESC);
