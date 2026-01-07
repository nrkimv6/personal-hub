-- 시스템 상태 캐시 테이블 (2025-01-08)
-- 시스템 현황 대시보드 성능 개선용
-- 1분 간격 백그라운드 수집 → DB 캐시 → API 즉시 반환

CREATE TABLE IF NOT EXISTS system_status_cache (
    id INTEGER PRIMARY KEY,
    data TEXT NOT NULL,                    -- JSON: {projects: {...}}
    collected_at TIMESTAMP NOT NULL,       -- 수집 시각
    collection_duration_ms INTEGER,        -- 수집 소요 시간 (ms)
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 초기 레코드 (싱글톤)
INSERT OR IGNORE INTO system_status_cache (id, data, collected_at, collection_duration_ms)
VALUES (1, '{"projects":{}}', CURRENT_TIMESTAMP, 0);
