-- 075: Writing Rotation System
-- 글쓰기 소재 로테이션을 위한 요소 관리 및 사용 이력 테이블

-- 1. 글쓰기 요소 마스터 테이블
CREATE TABLE IF NOT EXISTS writing_elements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category VARCHAR(20) NOT NULL,  -- 'topic', 'keyword', 'tone', 'style', 'format', 'emotion'
    name VARCHAR(100) NOT NULL,
    season_hint VARCHAR(50),        -- 시즌 힌트 (예: "spring,fall" 또는 NULL)
    is_active INTEGER DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(category, name)
);

-- 2. 요소 사용 이력 테이블
CREATE TABLE IF NOT EXISTS writing_element_usages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    element_id INTEGER,             -- writing_elements.id (NULL이면 source)
    source_id INTEGER,              -- writing_sources.id (NULL이면 element)
    generated_writing_id INTEGER NOT NULL,
    used_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (element_id) REFERENCES writing_elements(id) ON DELETE CASCADE,
    FOREIGN KEY (source_id) REFERENCES writing_sources(id) ON DELETE CASCADE,
    FOREIGN KEY (generated_writing_id) REFERENCES generated_writings(id) ON DELETE CASCADE
);

-- 3. generated_writings에 selected_elements 컬럼 추가
ALTER TABLE generated_writings ADD COLUMN selected_elements TEXT;

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_writing_elements_category ON writing_elements(category);
CREATE INDEX IF NOT EXISTS idx_writing_elements_category_active ON writing_elements(category, is_active);
CREATE INDEX IF NOT EXISTS idx_element_usages_element_used_at ON writing_element_usages(element_id, used_at);
CREATE INDEX IF NOT EXISTS idx_element_usages_source_used_at ON writing_element_usages(source_id, used_at);
CREATE INDEX IF NOT EXISTS idx_element_usages_generated_writing ON writing_element_usages(generated_writing_id);

-- 4. Seed Data: 소재 (topic)
INSERT OR IGNORE INTO writing_elements (category, name, season_hint) VALUES
    ('topic', '계절의 변화와 세월', 'spring,fall'),
    ('topic', '손주와의 일상', 'summer'),
    ('topic', '오래된 물건에 담긴 기억', 'fall,winter'),
    ('topic', '젊은 시절 꿈꿨던 것', NULL),
    ('topic', '건강과 몸의 변화', NULL),
    ('topic', '오랜 친구와의 추억', 'fall'),
    ('topic', '요즘 젊은 세대에 대한 생각', NULL),
    ('topic', '퇴직 후의 일상', NULL),
    ('topic', '부부의 소소한 순간', 'winter'),
    ('topic', '고향/옛 동네 풍경', 'fall,chuseok'),
    ('topic', '자식 키우며 겪었던 일', 'parents_day'),
    ('topic', '취미생활 (텃밭, 등산, 서예 등)', 'spring,summer');

-- 5. Seed Data: 키워드 (keyword)
INSERT OR IGNORE INTO writing_elements (category, name, season_hint) VALUES
    ('keyword', '기다림', NULL),
    ('keyword', '그리움', 'fall,chuseok'),
    ('keyword', '위로', NULL),
    ('keyword', '감사', 'parents_day,winter'),
    ('keyword', '여유', 'summer'),
    ('keyword', '담담함', NULL),
    ('keyword', '쓸쓸함', 'fall,winter'),
    ('keyword', '따뜻함', 'winter'),
    ('keyword', '변화', 'spring'),
    ('keyword', '적응', NULL),
    ('keyword', '수용', NULL),
    ('keyword', '놓아줌', NULL),
    ('keyword', '지혜', NULL),
    ('keyword', '후회', NULL),
    ('keyword', '용서', NULL),
    ('keyword', '화해', NULL),
    ('keyword', '건강', NULL),
    ('keyword', '고독', 'fall,winter'),
    ('keyword', '동행', NULL),
    ('keyword', '연결', NULL),
    ('keyword', '추억', 'fall,chuseok'),
    ('keyword', '현재', NULL),
    ('keyword', '미래', 'spring'),
    ('keyword', '시간', NULL),
    ('keyword', '자연', 'spring,summer'),
    ('keyword', '고요', NULL),
    ('keyword', '평온', NULL),
    ('keyword', '울림', NULL);

-- 6. Seed Data: 톤 (tone)
INSERT OR IGNORE INTO writing_elements (category, name, season_hint) VALUES
    ('tone', '잔잔한 회상', 'fall'),
    ('tone', '담담한 깨달음', NULL),
    ('tone', '따뜻한 위로', 'winter'),
    ('tone', '솔직한 고백', NULL),
    ('tone', '유머러스한 일상', 'summer'),
    ('tone', '서정적인 묘사', 'spring,fall'),
    ('tone', '조용한 감사', 'parents_day');

-- 7. Seed Data: 문체 (style)
INSERT OR IGNORE INTO writing_elements (category, name, season_hint) VALUES
    ('style', '짧고 간결한 문장', NULL),
    ('style', '여유로운 긴 문장', NULL),
    ('style', '대화체 혼합', NULL),
    ('style', '시적인 표현', 'spring,fall'),
    ('style', '일기체', NULL);

-- 8. Seed Data: 형식 (format)
INSERT OR IGNORE INTO writing_elements (category, name, season_hint) VALUES
    ('format', '짧은 에세이 (300-500자)', NULL),
    ('format', '중간 길이 글 (600-900자)', NULL),
    ('format', '편지 형식', 'parents_day'),
    ('format', '독백/혼잣말', NULL),
    ('format', '장면 묘사 중심', NULL),
    ('format', '대화 중심', NULL),
    ('format', '시 형식', 'spring,fall');

-- 9. Seed Data: 감정선 (emotion)
INSERT OR IGNORE INTO writing_elements (category, name, season_hint) VALUES
    ('emotion', '잔잔→따뜻함', 'winter'),
    ('emotion', '쓸쓸함→위안', 'fall'),
    ('emotion', '그리움→감사', 'chuseok,parents_day'),
    ('emotion', '답답함→수용', NULL),
    ('emotion', '평온→깨달음', NULL),
    ('emotion', '슬픔→희망', 'spring');
