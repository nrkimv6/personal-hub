-- GraphQL API 상세정보 필드 추가 마이그레이션
-- 생성일: 2025-12-03
-- 요구사항: REQ-DATA-004 (업체/상품 상세정보 조회)
-- 설명: URL 임포트 시 네이버 GraphQL API로 조회한 상세정보를 저장하기 위한 컬럼 추가

-- ============================================
-- 1. businesses 테이블 컬럼 추가
-- ============================================

-- 네이버 플레이스 ID
ALTER TABLE businesses ADD COLUMN place_id TEXT;

-- 서비스명 (예: "디저트 뮤지엄 DESSERT MUSEUM")
ALTER TABLE businesses ADD COLUMN service_name TEXT;

-- 위치 정보
ALTER TABLE businesses ADD COLUMN road_address TEXT;
ALTER TABLE businesses ADD COLUMN jibun_address TEXT;
ALTER TABLE businesses ADD COLUMN detail_address TEXT;
ALTER TABLE businesses ADD COLUMN latitude REAL;
ALTER TABLE businesses ADD COLUMN longitude REAL;

-- 연락처 정보
ALTER TABLE businesses ADD COLUMN phone TEXT;

-- API 동기화 시간 추적
ALTER TABLE businesses ADD COLUMN api_synced_at TIMESTAMP;

-- ============================================
-- 2. biz_items 테이블 컬럼 추가
-- ============================================

-- 상품 설명
ALTER TABLE biz_items ADD COLUMN description TEXT;

-- 아이템 타입 정보
ALTER TABLE biz_items ADD COLUMN biz_item_type TEXT;
ALTER TABLE biz_items ADD COLUMN biz_item_sub_type TEXT;
ALTER TABLE biz_items ADD COLUMN booking_count_type TEXT;

-- 예약 인원 범위
ALTER TABLE biz_items ADD COLUMN min_booking_count INTEGER;
ALTER TABLE biz_items ADD COLUMN max_booking_count INTEGER;

-- 상품 기간
ALTER TABLE biz_items ADD COLUMN start_date TEXT;
ALTER TABLE biz_items ADD COLUMN end_date TEXT;

-- 상세정보 JSON
ALTER TABLE biz_items ADD COLUMN extra_desc_json TEXT;
ALTER TABLE biz_items ADD COLUMN booking_precaution_json TEXT;

-- API 동기화 시간 추적
ALTER TABLE biz_items ADD COLUMN api_synced_at TIMESTAMP;

-- ============================================
-- 3. 인덱스 추가 (선택적)
-- ============================================

-- 위치 기반 검색을 위한 인덱스 (추후 활용)
CREATE INDEX IF NOT EXISTS idx_businesses_latitude ON businesses(latitude);
CREATE INDEX IF NOT EXISTS idx_businesses_longitude ON businesses(longitude);

-- API 동기화 상태 추적
CREATE INDEX IF NOT EXISTS idx_businesses_api_synced_at ON businesses(api_synced_at);
CREATE INDEX IF NOT EXISTS idx_biz_items_api_synced_at ON biz_items(api_synced_at);
