-- Plan Archive insight report review fields

ALTER TABLE plan_archive_insight_reports
    ADD COLUMN review_status VARCHAR(30) NOT NULL DEFAULT 'unreviewed';
ALTER TABLE plan_archive_insight_reports
    ADD COLUMN review_note TEXT;
ALTER TABLE plan_archive_insight_reports
    ADD COLUMN promoted_plan_path VARCHAR(1000);

CREATE INDEX IF NOT EXISTS ix_plan_archive_insight_reports_review_status
    ON plan_archive_insight_reports(review_status);
