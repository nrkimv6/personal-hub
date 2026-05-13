"""Services 단위 TC — SQLite in-memory DB 사용 (JSONB → JSON 패치)."""
import pytest
from sqlalchemy import create_engine, JSON
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.modules.list_board.models import ListBoardItem, ListBoardColumn
from app.modules.list_board.schemas import ListBoardImportRequest
from app.modules.list_board import services


def _patch_jsonb_to_json():
    """JSONB 컬럼을 SQLite 호환 JSON 타입으로 교체."""
    from sqlalchemy import JSON as SA_JSON

    for col in ListBoardItem.__table__.columns:
        if hasattr(col.type, "__class__") and col.type.__class__.__name__ == "JSONB":
            col.type = SA_JSON()
    for col in ListBoardColumn.__table__.columns:
        if hasattr(col.type, "__class__") and col.type.__class__.__name__ == "JSONB":
            col.type = SA_JSON()


@pytest.fixture
def db():
    _patch_jsonb_to_json()
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def test_import_creates_new_items(db):
    req = ListBoardImportRequest(
        markdown_text=(
            "| Course | Duration |\n"
            "|--------|----------|\n"
            "| [Course A](https://example.com/a) | 30 minutes |\n"
            "| [Course B](https://example.com/b) | 1 hour |"
        ),
        source="test",
    )
    result = services.import_items(db, req)
    assert result.created == 2
    assert result.updated == 0


def test_import_upsert_preserves_properties(db):
    req = ListBoardImportRequest(
        markdown_text=(
            "| Course | Duration |\n"
            "|--------|----------|\n"
            "| [Course A](https://example.com/a) | 30 minutes |"
        ),
        source="test",
    )
    services.import_items(db, req)

    # 직접 properties 설정
    item = db.query(ListBoardItem).filter_by(url="https://example.com/a").first()
    item.properties = {"my_note": "keep this"}
    db.commit()

    # 재import
    result = services.import_items(db, req)
    assert result.updated == 1
    item = db.query(ListBoardItem).filter_by(url="https://example.com/a").first()
    assert item.properties == {"my_note": "keep this"}


def test_list_items_filter_by_source(db):
    req_a = ListBoardImportRequest(
        markdown_text=(
            "| Course | Duration |\n"
            "|--------|----------|\n"
            "| [Course A](https://example.com/a) | 30 minutes |"
        ),
        source="source_a",
    )
    req_b = ListBoardImportRequest(
        markdown_text=(
            "| Course | Duration |\n"
            "|--------|----------|\n"
            "| [Course B](https://example.com/b) | 1 hour |"
        ),
        source="source_b",
    )
    services.import_items(db, req_a)
    services.import_items(db, req_b)
    result = services.list_items(db, source="source_a")
    assert result.total == 1
    assert result.items[0].source == "source_a"
