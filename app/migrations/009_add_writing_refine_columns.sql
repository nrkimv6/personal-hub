-- 글쓰기 교정 기능을 위한 컬럼 추가
-- 작성일: 2025-01-08

ALTER TABLE generated_writings ADD COLUMN refined_content TEXT;
ALTER TABLE generated_writings ADD COLUMN refined_at DATETIME;
