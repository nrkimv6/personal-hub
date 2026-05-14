"""Static and metadata checks for llm_requests child FK ondelete contracts."""

from pathlib import Path

from app.models.writing import GeneratedWriting
from app.modules.reports.models.generated_report import GeneratedReport

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = PROJECT_ROOT / "app" / "migrations" / "2026-05-14_llm_request_fk_set_null.sql"


def _fk_ondelete(column) -> str | None:
    [foreign_key] = list(column.foreign_keys)
    return foreign_key.ondelete


def test_generated_writing_fk_R_ondelete_set_null():
    assert _fk_ondelete(GeneratedWriting.__table__.c.llm_request_id) == "SET NULL"


def test_generated_report_fk_R_ondelete_set_null():
    assert _fk_ondelete(GeneratedReport.__table__.c.llm_request_id) == "SET NULL"


def test_writings_fk_R_no_code_surface():
    scanned_files = list((PROJECT_ROOT / "app" / "models").rglob("*.py"))
    scanned_files += list((PROJECT_ROOT / "app" / "modules").rglob("*.py"))
    scanned_files += list((PROJECT_ROOT / "app" / "migrations").rglob("*.sql"))
    matches = []
    for path in scanned_files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "writings.llm_request_id" in text or "__tablename__ = \"writings\"" in text:
            matches.append(str(path.relative_to(PROJECT_ROOT)))

    assert matches == []


def test_llm_request_fk_columns_B_nullable():
    assert GeneratedWriting.__table__.c.llm_request_id.nullable is True
    assert GeneratedReport.__table__.c.llm_request_id.nullable is True


def test_llm_request_fk_migration_R_recreates_two_constraints():
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "generated_writings" in sql
    assert "generated_reports" in sql
    assert sql.count("ON DELETE SET NULL") == 2


def test_llm_request_fk_migration_B_drops_existing_constraints():
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "DROP CONSTRAINT IF EXISTS generated_writings_llm_request_id_fkey" in sql
    assert "DROP CONSTRAINT IF EXISTS generated_reports_llm_request_id_fkey" in sql


def test_llm_request_fk_migration_E_no_cascade_for_child_rows():
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "ON DELETE CASCADE" not in sql
