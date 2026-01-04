-- 086_topic_auto_collect.sql
-- 소재(Topic) 자동 수집 시스템

-- 1. writing_elements에 source_type 컬럼 추가
-- seed: 기존 시드 데이터, auto: 자동 추출, manual: 수동 추가
ALTER TABLE writing_elements ADD COLUMN source_type VARCHAR(20) DEFAULT 'seed';

-- 2. generated_writings에 extracted_topics 컬럼 추가
-- Mix Writing에서 추출된 소재 JSON 저장
ALTER TABLE generated_writings ADD COLUMN extracted_topics TEXT;

-- 3. writing_sources에 topic_extracted_at 컬럼 추가
-- 소재 추출 완료 시간 (중복 처리 방지)
ALTER TABLE writing_sources ADD COLUMN topic_extracted_at DATETIME;

-- 4. 인덱스 추가
CREATE INDEX IF NOT EXISTS idx_writing_elements_source_type ON writing_elements(source_type);
CREATE INDEX IF NOT EXISTS idx_writing_sources_topic_extracted_at ON writing_sources(topic_extracted_at);
