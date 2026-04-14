-- Migration: Add http_method to proxy_usage_logs
-- Date: 2026-04-14
-- Description: 프록시 사용 이력에 실제 HTTP 메서드(get/post) 저장 컬럼 추가

ALTER TABLE proxy_usage_logs
ADD COLUMN http_method TEXT;
