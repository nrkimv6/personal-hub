-- 077: Writing Stopwords Table
-- 키워드 추출 시 제외할 불용어 관리

CREATE TABLE IF NOT EXISTS writing_stopwords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word TEXT NOT NULL UNIQUE,
    category VARCHAR(20) DEFAULT 'general',  -- 'template', 'ui', 'general'
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_stopwords_word ON writing_stopwords(word);
CREATE INDEX IF NOT EXISTS idx_stopwords_category ON writing_stopwords(category);

-- 초기 불용어 데이터 (블로그 템플릿/UI 관련)
INSERT OR IGNORE INTO writing_stopwords (word, category) VALUES
    ('스크랩', 'template'),
    ('인쇄', 'template'),
    ('신청', 'template'),
    ('이미지', 'template'),
    ('편지지', 'template'),
    ('개설', 'template'),
    ('영상', 'template'),
    ('카테고리', 'ui'),
    ('댓글', 'ui'),
    ('공감', 'ui'),
    ('구독', 'ui'),
    ('확인', 'ui'),
    ('이웃', 'ui'),
    ('팔로우', 'ui'),
    ('공유', 'ui');
