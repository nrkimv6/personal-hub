-- 이벤트 본문(body_text) 필드 추가
-- Instagram caption, 웹페이지 본문 등 전체 텍스트 검색용

-- 1. body_text 컬럼 추가
ALTER TABLE events ADD COLUMN body_text TEXT;

-- 2. 기존 Instagram 출처 이벤트에 caption 복사
UPDATE events
SET body_text = (
    SELECT caption FROM instagram_posts
    WHERE instagram_posts.id = events.source_instagram_post_id
)
WHERE source_instagram_post_id IS NOT NULL AND body_text IS NULL;
