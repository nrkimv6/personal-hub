-- Migration 056: entity_sources 테이블 생성 및 다중 출처 지원
-- 이벤트/팝업의 다중 출처(Instagram, 웹 크롤링 등)를 통합 관리

-- 1. entity_sources 테이블 생성
CREATE TABLE IF NOT EXISTS entity_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 엔티티 참조 (다형성)
    entity_type TEXT NOT NULL,      -- 'event' | 'popup'
    entity_id INTEGER NOT NULL,     -- events.id 또는 popups.id

    -- 출처 유형 및 참조
    source_type TEXT NOT NULL,      -- 'instagram' | 'web' | 'manual'
    source_id INTEGER,              -- instagram_posts.id 또는 crawled_pages.id
    source_url TEXT,                -- 원본 URL
    source_account TEXT,            -- 계정명/사이트명

    -- 출처 메타정보
    priority INTEGER DEFAULT 50,    -- 우선순위 (1-100, 높을수록 신뢰도 높음)
    is_primary INTEGER DEFAULT 0,   -- 대표 출처 여부
    contributed_fields TEXT,        -- JSON: 이 출처에서 가져온 필드 목록

    -- 추출 정보 (LLM 분석 결과 원본)
    extracted_data TEXT,            -- JSON: 이 출처에서 추출한 원본 데이터

    -- 메타데이터
    discovered_at TEXT DEFAULT CURRENT_TIMESTAMP,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,

    -- 제약조건
    UNIQUE(entity_type, entity_id, source_type, source_id)
);

CREATE INDEX IF NOT EXISTS idx_entity_sources_entity
    ON entity_sources(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_sources_source
    ON entity_sources(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_entity_sources_primary
    ON entity_sources(is_primary);

-- 2. events 테이블에 컬럼 추가
ALTER TABLE events ADD COLUMN source_count INTEGER DEFAULT 1;
ALTER TABLE events ADD COLUMN primary_source_id INTEGER REFERENCES entity_sources(id);
ALTER TABLE events ADD COLUMN confidence_score INTEGER DEFAULT 50;
ALTER TABLE events ADD COLUMN merged_from TEXT;  -- JSON: 병합된 ID 목록

-- 3. popups 테이블에 컬럼 추가
ALTER TABLE popups ADD COLUMN source_count INTEGER DEFAULT 1;
ALTER TABLE popups ADD COLUMN primary_source_id INTEGER REFERENCES entity_sources(id);
ALTER TABLE popups ADD COLUMN confidence_score INTEGER DEFAULT 50;
ALTER TABLE popups ADD COLUMN merged_from TEXT;  -- JSON: 병합된 ID 목록

-- 4. 기존 events 데이터 마이그레이션 (source_type이 있는 것만)
INSERT INTO entity_sources (
    entity_type, entity_id, source_type, source_id,
    source_url, source_account, priority, is_primary
)
SELECT
    'event',
    id,
    source_type,
    source_instagram_post_id,
    COALESCE(source_instagram_url, source_url),
    source_instagram_account,
    CASE source_type
        WHEN 'instagram' THEN 50
        WHEN 'web' THEN 60
        WHEN 'manual' THEN 20
        ELSE 30
    END,
    1
FROM events
WHERE source_type IS NOT NULL;

-- 5. 기존 popups 데이터 마이그레이션
INSERT INTO entity_sources (
    entity_type, entity_id, source_type, source_id,
    source_url, source_account, priority, is_primary
)
SELECT
    'popup',
    id,
    source_type,
    source_instagram_post_id,
    source_instagram_url,
    source_instagram_account,
    CASE source_type
        WHEN 'instagram' THEN 50
        WHEN 'web' THEN 60
        WHEN 'manual' THEN 20
        ELSE 30
    END,
    1
FROM popups
WHERE source_type IS NOT NULL;

-- 6. primary_source_id 업데이트
UPDATE events SET
    primary_source_id = (
        SELECT id FROM entity_sources
        WHERE entity_sources.entity_type = 'event'
        AND entity_sources.entity_id = events.id
        AND entity_sources.is_primary = 1
        LIMIT 1
    )
WHERE EXISTS (
    SELECT 1 FROM entity_sources
    WHERE entity_sources.entity_type = 'event'
    AND entity_sources.entity_id = events.id
);

UPDATE popups SET
    primary_source_id = (
        SELECT id FROM entity_sources
        WHERE entity_sources.entity_type = 'popup'
        AND entity_sources.entity_id = popups.id
        AND entity_sources.is_primary = 1
        LIMIT 1
    )
WHERE EXISTS (
    SELECT 1 FROM entity_sources
    WHERE entity_sources.entity_type = 'popup'
    AND entity_sources.entity_id = popups.id
);
