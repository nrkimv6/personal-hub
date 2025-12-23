-- 팝업스토어 위치 정보 컬럼 추가
-- 팝업 태그 게시물에만 사용됨
-- 형식: {"venue_name": "장소명", "address": "주소"}
ALTER TABLE instagram_posts ADD COLUMN llm_location JSON;
