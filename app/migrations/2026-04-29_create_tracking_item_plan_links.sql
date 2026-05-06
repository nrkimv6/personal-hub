-- Tracking 항목 ↔ Plan 레코드 N:N 링크 테이블
CREATE TABLE IF NOT EXISTS tracking_item_plan_links (
    id SERIAL PRIMARY KEY,
    tracking_item_id INTEGER NOT NULL REFERENCES tracking_items(id) ON DELETE CASCADE,
    plan_record_id INTEGER NOT NULL REFERENCES plan_records(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (tracking_item_id, plan_record_id)
);
CREATE INDEX IF NOT EXISTS ix_tracking_links_tracking_id ON tracking_item_plan_links(tracking_item_id);
CREATE INDEX IF NOT EXISTS ix_tracking_links_plan_record_id ON tracking_item_plan_links(plan_record_id);
