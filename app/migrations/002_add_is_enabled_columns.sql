-- businesses, biz_items 테이블에 is_enabled 컬럼 추가
-- 생성일: 2025-12-03
-- 요구사항: REQ-MGT-005 (계층별 활성화/비활성화)
-- 설명: 업체/상품 단위로 모니터링을 일괄 활성화/비활성화하기 위한 컬럼

-- ============================================
-- 1. businesses 테이블 is_enabled 추가
-- ============================================
ALTER TABLE businesses ADD COLUMN is_enabled INTEGER DEFAULT 1;

-- ============================================
-- 2. biz_items 테이블 is_enabled 추가
-- ============================================
ALTER TABLE biz_items ADD COLUMN is_enabled INTEGER DEFAULT 1;
