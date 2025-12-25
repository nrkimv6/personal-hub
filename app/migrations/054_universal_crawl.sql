-- 054: Universal Crawl Queue System
-- 범용 URL 크롤링 큐 시스템

-- 크롤링된 페이지 결과 저장 (먼저 생성 - FK 참조 대상)
CREATE TABLE IF NOT EXISTS crawled_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 원본 정보
    url TEXT NOT NULL,
    url_type TEXT NOT NULL,  -- google_form, naver_form, naver_blog, generic

    -- 추출 결과
    title TEXT,
    description TEXT,
    content TEXT,              -- 본문 텍스트
    extracted_data TEXT,       -- JSON: 구조화된 데이터 (폼 질문, 이미지 등)

    -- 메타데이터
    og_title TEXT,
    og_description TEXT,
    og_image TEXT,

    -- 상태
    crawled_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    extractor_used TEXT,       -- 사용된 추출기 이름

    -- AI 분석 결과 (선택적)
    is_event BOOLEAN,
    event_id INTEGER,          -- FK to events (분석 후 생성된 이벤트)
    analysis_result TEXT,      -- JSON: LLM 분석 결과

    -- 중복 방지
    url_hash TEXT UNIQUE,      -- MD5(url) for dedup

    FOREIGN KEY (event_id) REFERENCES events(id)
);

-- 범용 크롤링 요청 큐
CREATE TABLE IF NOT EXISTS universal_crawl_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 요청 정보
    url TEXT NOT NULL,
    url_type TEXT NOT NULL DEFAULT 'other',  -- google_form, naver_form, naver_blog, generic

    -- 브라우저 프로필 (Playwright 기반 크롤링용)
    account_id INTEGER,  -- FK to accounts, 브라우저 프로필 지정
                         -- NULL이면 기본 프로필 사용 또는 HTTP만 사용
                         -- 로그인 필요한 사이트(구글 등)는 지정 필요

    -- 요청 상태
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, processing, completed, failed
    requested_by TEXT DEFAULT 'manual',      -- manual, pwa_share, api
    requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- 처리 정보
    started_at DATETIME,
    completed_at DATETIME,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,

    -- 결과 연결
    crawled_page_id INTEGER,  -- FK to crawled_pages

    -- 옵션
    auto_analyze BOOLEAN DEFAULT TRUE,       -- AI 분석 자동 실행 여부
    priority INTEGER DEFAULT 0,              -- 우선순위 (높을수록 먼저)

    -- 메타데이터
    metadata TEXT,  -- JSON: 추가 정보 (referrer, source 등)

    FOREIGN KEY (crawled_page_id) REFERENCES crawled_pages(id),
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

-- 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_crawled_pages_url_hash ON crawled_pages(url_hash);
CREATE INDEX IF NOT EXISTS idx_crawled_pages_url_type ON crawled_pages(url_type);
CREATE INDEX IF NOT EXISTS idx_crawled_pages_crawled_at ON crawled_pages(crawled_at);

CREATE INDEX IF NOT EXISTS idx_universal_crawl_status ON universal_crawl_requests(status);
CREATE INDEX IF NOT EXISTS idx_universal_crawl_url_type ON universal_crawl_requests(url_type);
CREATE INDEX IF NOT EXISTS idx_universal_crawl_requested_at ON universal_crawl_requests(requested_at);
CREATE INDEX IF NOT EXISTS idx_universal_crawl_account_id ON universal_crawl_requests(account_id);
CREATE INDEX IF NOT EXISTS idx_universal_crawl_priority_status ON universal_crawl_requests(priority DESC, status, requested_at);
