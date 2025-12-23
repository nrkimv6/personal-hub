-- URL 기반 크롤링 관련 필드 추가
-- 2024-12-22

-- instagram_crawl_requests에 url_type 컬럼 추가
-- URL 타입: main_feed, account_profile, account_reels, single_post, single_reel, reels_explore, hashtag
ALTER TABLE instagram_crawl_requests ADD COLUMN url_type VARCHAR(50);

-- instagram_posts에 릴스 관련 메타데이터 추가 (선택적)
ALTER TABLE instagram_posts ADD COLUMN is_reel BOOLEAN DEFAULT FALSE;
ALTER TABLE instagram_posts ADD COLUMN duration REAL;  -- 재생 시간 (초)
ALTER TABLE instagram_posts ADD COLUMN music_title TEXT;  -- 사용된 음악 제목
ALTER TABLE instagram_posts ADD COLUMN music_artist TEXT;  -- 음악 아티스트

-- 인덱스 추가
CREATE INDEX IF NOT EXISTS idx_instagram_posts_is_reel ON instagram_posts(is_reel);
CREATE INDEX IF NOT EXISTS idx_instagram_crawl_requests_url_type ON instagram_crawl_requests(url_type);
