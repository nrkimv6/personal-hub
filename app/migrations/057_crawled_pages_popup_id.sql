-- Migration 057: crawled_pages 테이블에 popup_id 컬럼 추가
-- CrawledPage에서 Popup 자동 생성 시 연결용

ALTER TABLE crawled_pages ADD COLUMN popup_id INTEGER REFERENCES popups(id) ON DELETE SET NULL;
