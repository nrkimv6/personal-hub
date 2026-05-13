"""sort allowlist 및 fallback TC."""
import pytest
from sqlalchemy import create_engine, JSON as SA_JSON
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.modules.list_board.models import ListBoardColumn, ListBoardItem
from app.modules.list_board.schemas import ListBoardImportRequest
from app.modules.list_board import services

_MD = lambda title, url, dur: (
    f"| Course | Duration |\n"
    f"|--------|----------|\n"
    f"| [{title}]({url}) | {dur} |"
)


def _patch_jsonb():
    for col in ListBoardItem.__table__.columns:
        if col.type.__class__.__name__ == "JSONB":
            col.type = SA_JSON()
    for col in ListBoardColumn.__table__.columns:
        if col.type.__class__.__name__ == "JSONB":
            col.type = SA_JSON()


@pytest.fixture
def db():
    _patch_jsonb()
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture
def populated_db(db):
    for title, url, dur in [
        ("Alpha", "https://a.com", "10 minutes"),
        ("Gamma", "https://g.com", "90 minutes"),
        ("Beta", "https://b.com", "30 minutes"),
    ]:
        services.import_items(db, ListBoardImportRequest(markdown_text=_MD(title, url, dur), source="s"))
    return db


def test_sort_by_title_asc(populated_db):
    result = services.list_items(populated_db, sort_by="title", sort_order="asc")
    titles = [i.title for i in result.items]
    assert titles == sorted(titles)


def test_sort_by_title_desc(populated_db):
    result = services.list_items(populated_db, sort_by="title", sort_order="desc")
    titles = [i.title for i in result.items]
    assert titles == sorted(titles, reverse=True)


def test_sort_by_duration_asc(populated_db):
    result = services.list_items(populated_db, sort_by="duration_minutes", sort_order="asc")
    durations = [i.duration_minutes for i in result.items]
    assert durations == sorted(durations)


def test_sort_by_duration_desc(populated_db):
    result = services.list_items(populated_db, sort_by="duration_minutes", sort_order="desc")
    durations = [i.duration_minutes for i in result.items]
    assert durations == sorted(durations, reverse=True)


def test_sort_by_unknown_custom_key_fallback_no_error(populated_db):
    # 허용되지 않은 custom key는 fallback(created_at desc)으로 처리, 에러 없음
    result = services.list_items(populated_db, sort_by="unknown_custom_key", sort_order="asc")
    assert result.total == 3


def test_no_sort_returns_all(populated_db):
    result = services.list_items(populated_db)
    assert result.total == 3


def test_sort_order_case_insensitive_desc(populated_db):
    result = services.list_items(populated_db, sort_by="title", sort_order="DESC")
    titles = [i.title for i in result.items]
    assert titles == sorted(titles, reverse=True)
