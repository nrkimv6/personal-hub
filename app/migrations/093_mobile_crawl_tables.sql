-- 모바일 크롤링 테이블
-- Phase 4-7: Mobile Crawl 데이터 모델

-- 모바일 크롤링 대상
CREATE TABLE IF NOT EXISTS mobile_crawl_targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,                    -- 대상 이름 (사용자 지정 라벨)
    url TEXT NOT NULL UNIQUE,               -- 대상 URL
    crawl_type TEXT NOT NULL DEFAULT 'list', -- 크롤링 타입: 'list', 'detail'
    parse_config TEXT NOT NULL,             -- 파싱 설정 (JSON)
    is_active BOOLEAN NOT NULL DEFAULT 1,   -- 활성화 여부
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 모바일 크롤링 아이템
CREATE TABLE IF NOT EXISTS mobile_crawl_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id INTEGER NOT NULL,             -- 크롤링 대상 ID
    run_id INTEGER,                         -- 실행 ID (TaskScheduleRun)

    -- 아이템 기본 정보
    title TEXT NOT NULL,                    -- 아이템 제목
    item_url TEXT,                          -- 아이템 URL (상세 페이지 링크)
    image_url TEXT,                         -- 이미지 URL

    -- 아이템 속성 (JSON)
    attributes TEXT,                        -- 가변 속성 (가격, 상태, 날짜 등)

    -- 원본 데이터
    raw_html TEXT,                          -- 아이템 원본 HTML (선택)

    -- 변경 감지
    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- 최초 발견일
    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,   -- 최종 확인일
    is_changed BOOLEAN DEFAULT 0,           -- 변경 감지 여부

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (target_id) REFERENCES mobile_crawl_targets(id) ON DELETE CASCADE,
    FOREIGN KEY (run_id) REFERENCES task_schedule_runs(id) ON DELETE SET NULL
);

-- 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_mobile_crawl_items_target_id ON mobile_crawl_items(target_id);
CREATE INDEX IF NOT EXISTS idx_mobile_crawl_items_run_id ON mobile_crawl_items(run_id);
CREATE INDEX IF NOT EXISTS idx_mobile_crawl_items_item_url ON mobile_crawl_items(item_url);
CREATE INDEX IF NOT EXISTS idx_mobile_crawl_items_first_seen_at ON mobile_crawl_items(first_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_mobile_crawl_items_last_seen_at ON mobile_crawl_items(last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_mobile_crawl_targets_is_active ON mobile_crawl_targets(is_active);
