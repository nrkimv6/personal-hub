-- 053_add_event_input_source.sql
-- 이벤트 입력 출처 필드 추가 (AI/사람/AI수정)

-- events 테이블에 input_source 컬럼 추가
ALTER TABLE events ADD COLUMN input_source VARCHAR(20) DEFAULT 'human';

-- 인덱스 추가
CREATE INDEX IF NOT EXISTS idx_events_input_source ON events(input_source);

-- 기존 Instagram 출처 이벤트는 'ai'로 표시 (source_type이 instagram이고 source_instagram_post_id가 있는 경우)
UPDATE events
SET input_source = 'ai'
WHERE source_type = 'instagram'
  AND source_instagram_post_id IS NOT NULL
  AND input_source IS NULL;

-- popups 테이블에도 추가 (일관성)
ALTER TABLE popups ADD COLUMN input_source VARCHAR(20) DEFAULT 'human';
CREATE INDEX IF NOT EXISTS idx_popups_input_source ON popups(input_source);

UPDATE popups
SET input_source = 'ai'
WHERE source_type = 'instagram'
  AND source_instagram_post_id IS NOT NULL
  AND input_source IS NULL;
