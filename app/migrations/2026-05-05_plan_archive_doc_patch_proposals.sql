-- Plan Archive document patch proposal storage.

CREATE TABLE IF NOT EXISTS plan_archive_doc_patch_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_record_id INTEGER NOT NULL,
    insight_report_id INTEGER,
    status VARCHAR(30) NOT NULL DEFAULT 'draft',
    target_path VARCHAR(1000) NOT NULL,
    patch_text TEXT NOT NULL DEFAULT '',
    preview_text TEXT,
    changed_lines_summary JSON,
    applied_commit VARCHAR(80),
    error_message TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    applied_at DATETIME,
    CONSTRAINT ck_plan_archive_doc_patch_status CHECK (status IN ('draft', 'previewed', 'applied', 'rejected', 'failed')),
    FOREIGN KEY(plan_record_id) REFERENCES plan_records(id),
    FOREIGN KEY(insight_report_id) REFERENCES plan_archive_insight_reports(id)
);

CREATE INDEX IF NOT EXISTS ix_plan_archive_doc_patch_proposals_status
    ON plan_archive_doc_patch_proposals(status);
CREATE INDEX IF NOT EXISTS ix_plan_archive_doc_patch_proposals_record
    ON plan_archive_doc_patch_proposals(plan_record_id);
CREATE INDEX IF NOT EXISTS ix_plan_archive_doc_patch_proposals_report
    ON plan_archive_doc_patch_proposals(insight_report_id);
