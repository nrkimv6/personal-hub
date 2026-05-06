"""SQLAlchemy Base/bootstrap regression tests."""

from sqlalchemy import create_engine, inspect

from app.core.database import Base as CoreBase
from app.database import Base as CompatBase
from app.models.base import Base as ModelBase
from app.models import bootstrap as bootstrap_mod
from app.models.bootstrap import ensure_bootstrap_tables_loaded, load_all_models


def test_bases_share_single_registry():
    """`app.database`, `app.core.database`, `app.models.base`는 동일 Base를 가리킨다."""
    assert CompatBase is CoreBase
    assert ModelBase is CoreBase


def test_load_all_models_registers_split_tables():
    """notes/git_repos/claude_worker 모델이 공통 metadata에 등록된다."""
    load_all_models()

    expected_tables = {
        "notes",
        "note_tag_defs",
        "note_tags",
        "note_histories",
        "git_repos",
        "git_operation_logs",
        "llm_requests",
        "llm_worker_status",
        "writing_batches",
        "llm_request_profile_claims",
        "llm_profile_assignments",
        "llm_schedule_profile_policies",
        "plan_archive_execution_jobs",
        "plan_archive_execution_attempts",
    }

    assert expected_tables.issubset(set(CoreBase.metadata.tables))


def test_bootstrap_guard_fails_when_required_table_missing(monkeypatch):
    """guard는 필수 bootstrap 테이블 누락을 즉시 실패시킨다."""
    load_all_models()

    monkeypatch.setattr(
        bootstrap_mod,
        "REQUIRED_BOOTSTRAP_TABLES",
        set(bootstrap_mod.REQUIRED_BOOTSTRAP_TABLES) | {"missing_guard_table"},
    )

    try:
        ensure_bootstrap_tables_loaded()
    except RuntimeError as exc:
        assert "missing_guard_table" in str(exc)
    else:
        raise AssertionError("bootstrap guard must fail when a required table is missing")


def test_selected_create_all_handles_notes_git_repos_and_llm_fk():
    """선택 create_all이 notes/git_repos/llm FK 세트를 한 번에 생성한다."""
    load_all_models()

    engine = create_engine("sqlite:///:memory:")
    tables = [
        CoreBase.metadata.tables["note_tag_defs"],
        CoreBase.metadata.tables["notes"],
        CoreBase.metadata.tables["note_tags"],
        CoreBase.metadata.tables["note_histories"],
        CoreBase.metadata.tables["git_repos"],
        CoreBase.metadata.tables["git_operation_logs"],
        CoreBase.metadata.tables["writing_batches"],
        CoreBase.metadata.tables["plan_records"],
        CoreBase.metadata.tables["task_schedules"],
        CoreBase.metadata.tables["llm_requests"],
        CoreBase.metadata.tables["llm_worker_status"],
        CoreBase.metadata.tables["llm_request_profile_claims"],
        CoreBase.metadata.tables["llm_profile_assignments"],
        CoreBase.metadata.tables["llm_schedule_profile_policies"],
        CoreBase.metadata.tables["plan_archive_execution_jobs"],
        CoreBase.metadata.tables["plan_archive_execution_attempts"],
    ]

    CoreBase.metadata.create_all(bind=engine, tables=tables)

    try:
        created = set(inspect(engine).get_table_names())
        assert {
            "notes",
            "git_repos",
            "llm_requests",
            "writing_batches",
            "llm_schedule_profile_policies",
            "plan_archive_execution_jobs",
        }.issubset(created)
    finally:
        engine.dispose()
