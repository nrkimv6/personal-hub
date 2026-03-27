-- plan_records 테이블에 반복 감지 필드 추가
ALTER TABLE plan_records ADD COLUMN recurrence_count INTEGER DEFAULT 1;
ALTER TABLE plan_records ADD COLUMN chain_root_hash VARCHAR(64);
ALTER TABLE plan_records ADD COLUMN recurrence_suggestion TEXT;
