"""SQLAlchemy metadata bootstrap helpers."""

from app.core.database import Base


REQUIRED_BOOTSTRAP_TABLES = {
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
}


def ensure_bootstrap_tables_loaded() -> None:
    """Fail fast when shared metadata is missing required bootstrap tables."""
    missing = sorted(REQUIRED_BOOTSTRAP_TABLES - set(Base.metadata.tables))
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(f"SQLAlchemy bootstrap preload incomplete: {joined}")


def load_all_models():
    """Register app ORM models on the shared Base metadata."""
    import app.models as models  # noqa: F401

    ensure_bootstrap_tables_loaded()
    return models
