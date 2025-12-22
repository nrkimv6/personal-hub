-- Instagram 게시물에 LLM 분류 결과 컬럼 추가
-- llm_requests는 처리 큐로만 사용, 결과는 여기에 저장

-- LLM 분류 상태
ALTER TABLE instagram_posts ADD COLUMN llm_status TEXT;  -- pending/processing/completed/failed

-- LLM 분류 결과 (개별 컬럼)
ALTER TABLE instagram_posts ADD COLUMN llm_tag TEXT;  -- 이벤트/팝업/홍보대사/기타
ALTER TABLE instagram_posts ADD COLUMN llm_purchase_required TEXT;  -- 예_전부/예_부분/아니오
ALTER TABLE instagram_posts ADD COLUMN llm_prizes JSON;  -- ["경품1", "경품2"]
ALTER TABLE instagram_posts ADD COLUMN llm_winner_count INTEGER;
ALTER TABLE instagram_posts ADD COLUMN llm_event_start DATE;
ALTER TABLE instagram_posts ADD COLUMN llm_event_end DATE;
ALTER TABLE instagram_posts ADD COLUMN llm_announcement_date DATE;
ALTER TABLE instagram_posts ADD COLUMN llm_urls JSON;  -- ["https://..."]
ALTER TABLE instagram_posts ADD COLUMN llm_organizer TEXT;
ALTER TABLE instagram_posts ADD COLUMN llm_summary TEXT;
ALTER TABLE instagram_posts ADD COLUMN llm_analyzed_at DATETIME;

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_instagram_posts_llm_tag ON instagram_posts(llm_tag);
CREATE INDEX IF NOT EXISTS idx_instagram_posts_llm_status ON instagram_posts(llm_status);
