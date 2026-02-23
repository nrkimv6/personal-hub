-- ===== 파일 분류기 초기 스키마 =====
-- 카테고리, 파일 목록, 분류 규칙, 메타데이터 테이블 생성

-- ===== 카테고리 =====
CREATE TABLE IF NOT EXISTS fc_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES fc_categories(id),
    full_path TEXT NOT NULL UNIQUE,  -- "music/kpop"
    description TEXT,
    sort_order INTEGER DEFAULT 0
);

-- ===== 스캔된 파일 (핵심) =====
CREATE TABLE IF NOT EXISTS fc_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL UNIQUE,
    file_name TEXT NOT NULL,
    extension TEXT,              -- ".mp3", ".zip", ".exe"
    file_size INTEGER,
    file_modified_at DATETIME,
    file_hash TEXT,              -- SHA256 (선택적, 대용량은 스킵)

    -- 파일 타입 그룹
    file_group TEXT NOT NULL     -- "music", "archive", "document", "installer", "game", "misc"
        CHECK(file_group IN ('music','archive','document','installer','game','misc')),

    -- 메타데이터 (타입별)
    metadata_json TEXT,          -- JSON: 음악 태그, ZIP 내부 목록, PE 정보 등

    -- 분류 결과
    rule_category_id INTEGER REFERENCES fc_categories(id),   -- 규칙 기반 분류
    llm_category_id INTEGER REFERENCES fc_categories(id),    -- LLM 분류
    final_category_id INTEGER REFERENCES fc_categories(id),  -- 최종 (사용자 확정)
    llm_confidence REAL,
    llm_reasoning TEXT,

    -- 상태
    status TEXT DEFAULT 'pending'
        CHECK(status IN ('pending','metadata_extracted','rule_classified',
                         'llm_classified','approved','moved','error','skipped')),

    -- 이동
    suggested_path TEXT,         -- 제안된 이동 경로
    moved_path TEXT,             -- 실제 이동된 경로

    -- 추가 플래그
    is_deletable BOOLEAN DEFAULT FALSE,   -- 삭제 후보 (빌드 잔여, 오래된 로그 등)
    delete_reason TEXT,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    classified_at DATETIME,
    moved_at DATETIME
);

CREATE INDEX IF NOT EXISTS idx_fcf_status ON fc_files(status);
CREATE INDEX IF NOT EXISTS idx_fcf_group ON fc_files(file_group);
CREATE INDEX IF NOT EXISTS idx_fcf_ext ON fc_files(extension);
CREATE INDEX IF NOT EXISTS idx_fcf_category ON fc_files(final_category_id);

-- ===== 분류 규칙 =====
CREATE TABLE IF NOT EXISTS fc_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_type TEXT NOT NULL
        CHECK(rule_type IN ('extension','filename_pattern','folder_path',
                            'metadata_field','zip_content','pe_info')),
    category_id INTEGER NOT NULL REFERENCES fc_categories(id),
    rule_content TEXT NOT NULL,   -- JSON: {"field": "artist_lang", "value": "ja"} 등
    priority INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    hit_count INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ===== 음악 메타데이터 (정규화) =====
CREATE TABLE IF NOT EXISTS fc_music_meta (
    file_id INTEGER PRIMARY KEY REFERENCES fc_files(id),
    title TEXT,
    artist TEXT,
    album TEXT,
    genre TEXT,
    year INTEGER,
    duration_seconds INTEGER,
    bitrate INTEGER,
    artist_lang TEXT,     -- "ko", "ja", "en", "unknown" (자동 감지)
    has_tags BOOLEAN DEFAULT FALSE
);

-- ===== 압축파일 내부 목록 =====
CREATE TABLE IF NOT EXISTS fc_archive_contents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL REFERENCES fc_files(id),
    inner_path TEXT NOT NULL,     -- 압축 내부 파일 경로
    inner_size INTEGER,
    is_encrypted BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_fca_file ON fc_archive_contents(file_id);

-- ===== 설치파일 정보 =====
CREATE TABLE IF NOT EXISTS fc_installer_meta (
    file_id INTEGER PRIMARY KEY REFERENCES fc_files(id),
    product_name TEXT,
    company_name TEXT,
    file_version TEXT,
    is_installed BOOLEAN DEFAULT NULL,   -- 현재 시스템에 설치되어 있는지
    installed_version TEXT               -- 설치된 버전 (비교용)
);

-- ===== 작업 진행 상태 =====
CREATE TABLE IF NOT EXISTS fc_task_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type TEXT NOT NULL,      -- "scan", "metadata", "classify", "move"
    status TEXT DEFAULT 'pending'
        CHECK(status IN ('pending','running','completed','failed','paused')),
    total_items INTEGER DEFAULT 0,
    processed_items INTEGER DEFAULT 0,
    current_item TEXT,
    error_message TEXT,
    started_at DATETIME,
    completed_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ===== 옵시디언 노트 =====
CREATE TABLE IF NOT EXISTS obsidian_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL UNIQUE,
    file_name TEXT NOT NULL,
    file_size INTEGER,
    file_modified_at DATETIME,

    -- 파싱 결과
    has_frontmatter BOOLEAN DEFAULT FALSE,
    frontmatter_json TEXT,       -- YAML→JSON 변환
    content_length INTEGER,      -- 글자 수
    tags_json TEXT,              -- ["태그1", "태그2"]
    links_json TEXT,             -- ["[[링크1]]", "[[링크2]]"]
    is_daily_note BOOLEAN DEFAULT FALSE,

    -- LLM 분류
    note_type TEXT,              -- "memo", "record", "daily", "other"
    llm_confidence REAL,
    llm_reasoning TEXT,

    -- 추출 데이터
    extracted_json TEXT,         -- Phase 2 추출 결과

    status TEXT DEFAULT 'pending'
        CHECK(status IN ('pending','scanned','classified','extracted','reviewed')),

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_on_type ON obsidian_notes(note_type);
CREATE INDEX IF NOT EXISTS idx_on_status ON obsidian_notes(status)
