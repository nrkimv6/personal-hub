-- Instagram 게시물 분류 기능 마이그레이션
-- 태그 기반 게시물 분류 시스템 추가

-- 태그 정의 테이블
CREATE TABLE IF NOT EXISTS instagram_post_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,           -- 태그 이름 (event, popup_store)
    display_name TEXT NOT NULL,          -- 표시 이름 (이벤트, 팝업스토어)
    description TEXT,                    -- 설명
    color TEXT DEFAULT '#6b7280',        -- UI 표시 색상 (hex)
    is_active BOOLEAN DEFAULT TRUE,      -- 활성화 여부
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 태그별 키워드 테이블
CREATE TABLE IF NOT EXISTS instagram_tag_keywords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tag_id INTEGER NOT NULL REFERENCES instagram_post_tags(id) ON DELETE CASCADE,
    keyword TEXT NOT NULL,               -- 키워드
    is_regex BOOLEAN DEFAULT FALSE,      -- 정규식 여부
    is_case_sensitive BOOLEAN DEFAULT FALSE,  -- 대소문자 구분
    is_active BOOLEAN DEFAULT TRUE,      -- 활성화 여부
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tag_id, keyword)
);

-- 게시물-태그 관계 테이블 (N:M)
CREATE TABLE IF NOT EXISTS instagram_post_tag_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL REFERENCES instagram_posts(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES instagram_post_tags(id) ON DELETE CASCADE,
    matched_keywords TEXT,               -- 매칭된 키워드들 (JSON array)
    confidence REAL DEFAULT 1.0,         -- 신뢰도 (0.0 ~ 1.0, 향후 AI 사용 시)
    classified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(post_id, tag_id)
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_post_tag_relations_post_id
    ON instagram_post_tag_relations(post_id);
CREATE INDEX IF NOT EXISTS idx_post_tag_relations_tag_id
    ON instagram_post_tag_relations(tag_id);
CREATE INDEX IF NOT EXISTS idx_tag_keywords_tag_id
    ON instagram_tag_keywords(tag_id);
CREATE INDEX IF NOT EXISTS idx_instagram_post_tags_name
    ON instagram_post_tags(name);
CREATE INDEX IF NOT EXISTS idx_instagram_post_tags_is_active
    ON instagram_post_tags(is_active);

-- 초기 태그 데이터
INSERT OR IGNORE INTO instagram_post_tags (name, display_name, description, color) VALUES
    ('event', '이벤트', '이벤트, 추첨, 경품 관련 게시물', '#ef4444'),
    ('popup_store', '팝업스토어', '팝업스토어 소개 게시물', '#8b5cf6');

-- 초기 키워드 데이터 (event)
INSERT OR IGNORE INTO instagram_tag_keywords (tag_id, keyword)
SELECT id, '이벤트' FROM instagram_post_tags WHERE name = 'event';
INSERT OR IGNORE INTO instagram_tag_keywords (tag_id, keyword)
SELECT id, '추첨' FROM instagram_post_tags WHERE name = 'event';
INSERT OR IGNORE INTO instagram_tag_keywords (tag_id, keyword)
SELECT id, '당첨' FROM instagram_post_tags WHERE name = 'event';
INSERT OR IGNORE INTO instagram_tag_keywords (tag_id, keyword)
SELECT id, '경품' FROM instagram_post_tags WHERE name = 'event';
INSERT OR IGNORE INTO instagram_tag_keywords (tag_id, keyword)
SELECT id, '응모' FROM instagram_post_tags WHERE name = 'event';
INSERT OR IGNORE INTO instagram_tag_keywords (tag_id, keyword)
SELECT id, '럭키드로우' FROM instagram_post_tags WHERE name = 'event';
INSERT OR IGNORE INTO instagram_tag_keywords (tag_id, keyword)
SELECT id, '댓글이벤트' FROM instagram_post_tags WHERE name = 'event';
INSERT OR IGNORE INTO instagram_tag_keywords (tag_id, keyword)
SELECT id, '팔로우이벤트' FROM instagram_post_tags WHERE name = 'event';
INSERT OR IGNORE INTO instagram_tag_keywords (tag_id, keyword)
SELECT id, '리그램이벤트' FROM instagram_post_tags WHERE name = 'event';
INSERT OR IGNORE INTO instagram_tag_keywords (tag_id, keyword)
SELECT id, '좋아요이벤트' FROM instagram_post_tags WHERE name = 'event';
INSERT OR IGNORE INTO instagram_tag_keywords (tag_id, keyword)
SELECT id, 'event' FROM instagram_post_tags WHERE name = 'event';

-- 초기 키워드 데이터 (popup_store)
INSERT OR IGNORE INTO instagram_tag_keywords (tag_id, keyword)
SELECT id, '팝업' FROM instagram_post_tags WHERE name = 'popup_store';
INSERT OR IGNORE INTO instagram_tag_keywords (tag_id, keyword)
SELECT id, '팝업스토어' FROM instagram_post_tags WHERE name = 'popup_store';
INSERT OR IGNORE INTO instagram_tag_keywords (tag_id, keyword)
SELECT id, '팝업 스토어' FROM instagram_post_tags WHERE name = 'popup_store';
INSERT OR IGNORE INTO instagram_tag_keywords (tag_id, keyword)
SELECT id, '팝업매장' FROM instagram_post_tags WHERE name = 'popup_store';
INSERT OR IGNORE INTO instagram_tag_keywords (tag_id, keyword)
SELECT id, '팝업 매장' FROM instagram_post_tags WHERE name = 'popup_store';
INSERT OR IGNORE INTO instagram_tag_keywords (tag_id, keyword)
SELECT id, '플래그십' FROM instagram_post_tags WHERE name = 'popup_store';
INSERT OR IGNORE INTO instagram_tag_keywords (tag_id, keyword)
SELECT id, '플래그십스토어' FROM instagram_post_tags WHERE name = 'popup_store';
INSERT OR IGNORE INTO instagram_tag_keywords (tag_id, keyword)
SELECT id, 'popup' FROM instagram_post_tags WHERE name = 'popup_store';
INSERT OR IGNORE INTO instagram_tag_keywords (tag_id, keyword)
SELECT id, 'pop-up' FROM instagram_post_tags WHERE name = 'popup_store';
INSERT OR IGNORE INTO instagram_tag_keywords (tag_id, keyword)
SELECT id, 'pop up' FROM instagram_post_tags WHERE name = 'popup_store';
