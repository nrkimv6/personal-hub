-- 문화센터 초기 데이터 (홈플러스, 신세계)
-- 크롤러 테스트용 seed 데이터

-- 홈플러스 문화센터 (HTML 파싱 방식)
INSERT OR IGNORE INTO activity_centers (
    name, center_type, crawl_url, crawl_method, crawl_config, is_active
) VALUES (
    '홈플러스 문화센터',
    'mart',
    'https://mschool.homeplus.co.kr/Lecture/SearchResult',
    'static',
    '{"crawler_id": "homeplus", "max_pages": 500, "page_size": 20, "delay": 1.0}',
    1
);

-- 신세계 문화센터 (API 호출 방식)
INSERT OR IGNORE INTO activity_centers (
    name, center_type, crawl_url, crawl_method, crawl_config, is_active
) VALUES (
    '신세계 문화센터',
    'department',
    'https://sacademy.shinsegae.com',
    'api',
    '{"crawler_id": "shinsegae", "max_pages": 100, "page_size": 10, "delay": 1.0, "extra": {"store_codes": ["01", "03", "14", "18", "37"]}}',
    1
);
