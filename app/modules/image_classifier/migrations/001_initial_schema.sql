-- ===================================================================
-- 이미지 분류 시스템 초기 스키마
-- 생성일: 2026-02-12
-- 참조: image-classifier-plan-final.md Section 8
-- ===================================================================

-- ===== 카테고리 =====
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES categories(id),
    full_path TEXT NOT NULL UNIQUE,
    importance TEXT CHECK(importance IN ('high','medium','low')),
    target_folder_template TEXT,
    description TEXT,
    sort_order INTEGER DEFAULT 0
);

-- ===== 폴더 매핑 =====
CREATE TABLE IF NOT EXISTS folder_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_path TEXT NOT NULL UNIQUE,
    category_id INTEGER REFERENCES categories(id),
    is_mixed BOOLEAN DEFAULT FALSE,
    file_count INTEGER,
    folder_status TEXT DEFAULT 'unknown'
        CHECK(folder_status IN ('unknown','clear','unclear','flat','nested')),
    mapped_by TEXT DEFAULT 'user'
        CHECK(mapped_by IN ('user','ai_suggested','inherited')),
    parent_mapping_id INTEGER REFERENCES folder_mappings(id),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ===== 파일 분류 (핵심 테이블) =====
CREATE TABLE IF NOT EXISTS file_classifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL UNIQUE,
    file_hash TEXT NOT NULL,
    file_size INTEGER,
    file_modified_at DATETIME,

    -- 소스
    source_folder_id INTEGER REFERENCES folder_mappings(id),

    -- 날짜 메타데이터
    extracted_date DATETIME,
    date_source TEXT DEFAULT 'unknown'
        CHECK(date_source IN (
            'user_input','filename','exif_original',
            'exif_digitized','folder_name','file_modified','unknown'
        )),
    user_date DATE,
    user_location TEXT,

    -- 신뢰도
    date_trust_level TEXT DEFAULT 'unknown'
        CHECK(date_trust_level IN (
            'user_input','filename','exif_original',
            'exif_digitized','folder_name','file_modified','unknown'
        )),

    -- 분류
    ai_category_id INTEGER REFERENCES categories(id),
    ai_confidence REAL,
    ai_reasoning TEXT,
    ai_model TEXT,

    -- 사용자 최종
    final_category_id INTEGER REFERENCES categories(id),
    is_user_corrected BOOLEAN DEFAULT FALSE,
    importance TEXT DEFAULT 'medium'
        CHECK(importance IN ('high','medium','low')),

    -- 클러스터
    cluster_id INTEGER REFERENCES time_clusters(id),

    -- 상태
    status TEXT DEFAULT 'pending'
        CHECK(status IN (
            'pending','folder_mapped','ai_classified',
            'approved','moved','error'
        )),
    suggested_path TEXT,
    moved_path TEXT,

    classified_at DATETIME,
    approved_at DATETIME,
    moved_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 파일 분류 인덱스
CREATE INDEX IF NOT EXISTS idx_fc_status ON file_classifications(status);
CREATE INDEX IF NOT EXISTS idx_fc_category ON file_classifications(final_category_id);
CREATE INDEX IF NOT EXISTS idx_fc_hash ON file_classifications(file_hash);
CREATE INDEX IF NOT EXISTS idx_fc_date ON file_classifications(user_date);
CREATE INDEX IF NOT EXISTS idx_fc_importance ON file_classifications(importance);
CREATE INDEX IF NOT EXISTS idx_fc_cluster ON file_classifications(cluster_id);

-- ===== 시간 클러스터 =====
CREATE TABLE IF NOT EXISTS time_clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    start_time DATETIME,
    end_time DATETIME,
    file_count INTEGER,
    category_id INTEGER REFERENCES categories(id),
    is_classified BOOLEAN DEFAULT FALSE,
    classified_by TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tc_date ON time_clusters(date);

-- ===== 태그 시스템 =====
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    usage_count INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS file_tags (
    file_id INTEGER NOT NULL REFERENCES file_classifications(id),
    tag_id INTEGER NOT NULL REFERENCES tags(id),
    PRIMARY KEY (file_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_ft_tag ON file_tags(tag_id);

-- ===== 커스텀 속성 (EAV) =====
CREATE TABLE IF NOT EXISTS file_attributes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL REFERENCES file_classifications(id),
    attr_key TEXT NOT NULL,
    attr_value TEXT NOT NULL,
    UNIQUE(file_id, attr_key)
);

CREATE INDEX IF NOT EXISTS idx_fa_key ON file_attributes(attr_key);
CREATE INDEX IF NOT EXISTS idx_fa_kv ON file_attributes(attr_key, attr_value);

-- ===== 중복 그룹 =====
CREATE TABLE IF NOT EXISTS duplicate_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_hash TEXT NOT NULL,
    member_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending'
        CHECK(status IN ('pending','resolved','ignored')),
    kept_file_id INTEGER REFERENCES file_classifications(id),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS duplicate_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL REFERENCES duplicate_groups(id),
    file_id INTEGER NOT NULL REFERENCES file_classifications(id),
    phash_distance INTEGER,
    is_exact BOOLEAN DEFAULT FALSE,
    file_size INTEGER,
    resolution TEXT,
    quality_score REAL,
    UNIQUE(group_id, file_id)
);

CREATE INDEX IF NOT EXISTS idx_dm_group ON duplicate_members(group_id);
CREATE INDEX IF NOT EXISTS idx_dm_file ON duplicate_members(file_id);

-- ===== 이미지 특징 =====
CREATE TABLE IF NOT EXISTS image_features (
    file_id INTEGER PRIMARY KEY REFERENCES file_classifications(id),
    phash TEXT,
    clip_embedding BLOB,
    computed_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_if_phash ON image_features(phash);

-- ===== 유사도 캐시 =====
CREATE TABLE IF NOT EXISTS similarity_cache (
    file_id_a INTEGER,
    file_id_b INTEGER,
    phash_distance INTEGER,
    clip_similarity REAL,
    PRIMARY KEY (file_id_a, file_id_b)
);

-- ===== 분류 규칙 =====
CREATE TABLE IF NOT EXISTS classification_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_type TEXT NOT NULL
        CHECK(rule_type IN ('folder_path','filename','keyword','learned')),
    category_id INTEGER NOT NULL REFERENCES categories(id),
    rule_content TEXT NOT NULL,
    priority INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    source TEXT DEFAULT 'user'
        CHECK(source IN ('user','learned','ai_suggested')),
    hit_count INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ===== 피드백 =====
CREATE TABLE IF NOT EXISTS feedback_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL REFERENCES file_classifications(id),
    original_category_id INTEGER REFERENCES categories(id),
    corrected_category_id INTEGER NOT NULL REFERENCES categories(id),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ===== 파일명 패턴 =====
CREATE TABLE IF NOT EXISTS filename_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL,
    date_format TEXT,
    source_app TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    priority INTEGER DEFAULT 0
);

-- 초기 파일명 패턴 데이터 (Section 4.1 참조)
INSERT OR IGNORE INTO filename_patterns (pattern, date_format, source_app, priority) VALUES
    ('IMG_(\d{8})_(\d{6})', '%Y%m%d_%H%M%S', 'Standard Camera', 100),
    ('IMG-(\d{8})-WA(\d+)', '%Y%m%d', 'WhatsApp', 90),
    ('(\d{8})_(\d{6})', '%Y%m%d_%H%M%S', 'Generic', 80),
    ('SAVE_(\d{8})_(\d{6})', '%Y%m%d_%H%M%S', 'Generic', 80),
    ('(\d{4})(\d{2})(\d{2})_(\d{6})', '%Y%m%d_%H%M%S', 'Samsung', 95),
    ('IMG_(\d{4})', NULL, 'iPhone (sequence only)', 50),
    ('Photo (\d{4}-\d{2}-\d{2})', '%Y-%m-%d', 'iPhone', 85),
    ('Screenshot_(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})', '%Y-%m-%d-%H-%M-%S', 'Screenshot', 90),
    ('스크린샷 (\d{4})-(\d{2})-(\d{2})', '%Y-%m-%d', 'Screenshot (Korean)', 90),
    ('KakaoTalk_(\d{8})_(\d{6})', '%Y%m%d_%H%M%S', 'KakaoTalk', 95),
    ('(\d{4})-(\d{2})-(\d{2})', '%Y-%m-%d', 'Generic Date', 70),
    ('(\d{4})\.(\d{2})\.(\d{2})', '%Y.%m.%d', 'Generic Date (dot)', 70);

-- ===== 연도 메모 =====
CREATE TABLE IF NOT EXISTS year_annotations (
    year INTEGER PRIMARY KEY,
    memo TEXT NOT NULL
);

-- ===== API 사용량 =====
CREATE TABLE IF NOT EXISTS api_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    image_count INTEGER DEFAULT 0,
    estimated_cost_usd REAL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS api_limits (
    id INTEGER PRIMARY KEY,
    limit_type TEXT NOT NULL CHECK(limit_type IN ('daily','monthly')),
    max_cost_usd REAL,
    max_images INTEGER,
    is_active BOOLEAN DEFAULT TRUE
);

-- 초기 API 리밋 설정 (CLI 모드 기본)
INSERT OR IGNORE INTO api_limits (id, limit_type, max_cost_usd, max_images, is_active) VALUES
    (1, 'daily', 0, 0, FALSE),
    (2, 'monthly', 0, 0, FALSE);
