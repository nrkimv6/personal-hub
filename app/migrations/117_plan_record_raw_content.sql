-- Migration 117: PlanRecord에 raw_content + file_removed_at 컬럼 추가
-- DB-first archive 전환: raw_content가 진실원본, file_removed_at은 로테이션 마킹

ALTER TABLE plan_records ADD COLUMN raw_content TEXT;
ALTER TABLE plan_records ADD COLUMN file_removed_at TIMESTAMP;
