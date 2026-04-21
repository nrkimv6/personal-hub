"""SQLAlchemy Base/bootstrap integration regressions."""

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.bootstrap import load_all_models
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.git_repos.models import GitRepo
from app.modules.notes.models import Note
from app.modules.writing.models.writing_batch import WritingBatch


BOOTSTRAP_TABLES = [
    "note_tag_defs",
    "notes",
    "notes_archive",
    "note_tags",
    "note_histories",
    "git_repos",
    "git_operation_logs",
    "writing_batches",
    "llm_requests",
    "llm_worker_status",
]


def _bootstrap_sqlite_file(db_path):
    load_all_models()

    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    tables = [Base.metadata.tables[name] for name in BOOTSTRAP_TABLES]
    Base.metadata.create_all(bind=engine, tables=tables)

    session = sessionmaker(bind=engine)()
    return engine, session


def test_reopen_same_sqlite_file_repeats_bootstrap_without_setup_error(tmp_path):
    """같은 SQLite 파일을 다시 열어도 notes/git_repos/llm bootstrap이 유지된다."""
    db_path = tmp_path / "bootstrap-repeat.db"

    engine, session = _bootstrap_sqlite_file(db_path)
    try:
        note = Note(title="first bootstrap", content="notes ok")
        repo = GitRepo(path="D:/tmp/bootstrap-repo", alias="bootstrap")
        session.add_all([note, repo])
        session.commit()

        tables = set(inspect(engine).get_table_names())
        assert {"notes", "git_repos", "git_operation_logs", "llm_requests", "writing_batches"}.issubset(tables), (
            "notes only fix regression: repeated bootstrap must still create git_repos/git_operation_logs and llm tables"
        )
    finally:
        session.close()
        engine.dispose()

    engine, session = _bootstrap_sqlite_file(db_path)
    try:
        assert session.query(Note).count() == 1
        assert session.query(GitRepo).count() == 1

        batch = WritingBatch(status=WritingBatch.STATUS_PENDING)
        session.add(batch)
        session.flush()

        request = LLMRequest(
            caller_type="bootstrap_integration",
            caller_id="repeat-open",
            prompt="second bootstrap",
            status="pending",
            writing_batch_id=batch.id,
        )
        session.add(request)
        session.commit()

        saved = session.query(LLMRequest).filter_by(caller_id="repeat-open").one()
        assert saved.writing_batch_id == batch.id
    finally:
        session.close()
        engine.dispose()
