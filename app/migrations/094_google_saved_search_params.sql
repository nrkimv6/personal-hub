-- 구글 저장된 검색에 추가 검색 파라미터 컬럼 추가
-- search_params: JSON 문자열 (lr, cr, as_sitesearch, num 등)

ALTER TABLE google_saved_searches ADD COLUMN search_params TEXT DEFAULT NULL;

ALTER TABLE google_search_queue ADD COLUMN search_params TEXT DEFAULT NULL;
