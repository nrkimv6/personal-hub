-- 038: Add likes/comments columns to instagram_posts
-- 좋아요/댓글 수 컬럼 추가

ALTER TABLE instagram_posts ADD COLUMN likes INTEGER;
ALTER TABLE instagram_posts ADD COLUMN comments INTEGER;
