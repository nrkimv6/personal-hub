-- 게시물 유형(post_type) 컬럼 추가
-- NORMAL: 일반 게시물
-- SPONSORED: 광고 게시물 (유료 프로모션)
-- SUGGESTED: 추천 게시물 (알고리즘 추천)

ALTER TABLE instagram_posts ADD COLUMN post_type TEXT DEFAULT 'NORMAL';

-- 기존 데이터 마이그레이션: is_ad=1이면 SPONSORED
UPDATE instagram_posts SET post_type = 'SPONSORED' WHERE is_ad = 1;
UPDATE instagram_posts SET post_type = 'NORMAL' WHERE is_ad = 0 OR is_ad IS NULL;
