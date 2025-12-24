-- 052: InstagramPost에 classified_at 필드 추가
-- AI 분류 완료 시각을 저장하여 정렬에 사용

ALTER TABLE instagram_posts ADD COLUMN classified_at DATETIME;

-- 인덱스 추가 (정렬 성능)
CREATE INDEX IF NOT EXISTS idx_instagram_posts_classified_at ON instagram_posts(classified_at);

-- 기존 분류된 게시물에 대해 classified_at 백필
-- (llm_requests 테이블에서 처리 완료 시각을 가져옴)
UPDATE instagram_posts
SET classified_at = (
    SELECT lr.processed_at
    FROM llm_requests lr
    WHERE lr.caller_type = 'instagram'
    AND lr.caller_id = CAST(instagram_posts.id AS TEXT)
    AND lr.status = 'completed'
    ORDER BY lr.processed_at DESC
    LIMIT 1
)
WHERE classified_type IS NOT NULL
AND classified_at IS NULL;
