"""reimport 후 custom properties 보존 TC."""
import pytest
from sqlalchemy import create_engine, JSON as SA_JSON
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.modules.list_board.models import ListBoardColumn, ListBoardItem
from app.modules.list_board.schemas import ColumnCreate, ItemPropertiesPatch, ListBoardImportRequest
from app.modules.list_board import services

_MD = (
    "| Course | Duration |\n"
    "|--------|----------|\n"
    "| [Course A](https://example.com/a) | 30 minutes |"
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


def test_reimport_preserves_custom_properties(db):
    # initial import + patch
    services.import_items(db, ListBoardImportRequest(markdown_text=_MD, source="src"))
    item = db.query(ListBoardItem).first()
    services.create_column(db, ColumnCreate(key="done", display_name="완료", column_type="checkbox"))
    services.patch_item_properties(db, item.id, ItemPropertiesPatch(properties={"done": True}))

    # reimport — system fields 갱신, properties 보존
    result = services.import_items(db, ListBoardImportRequest(markdown_text=_MD, source="src"))
    assert result.updated == 1
    item = db.query(ListBoardItem).filter_by(url="https://example.com/a").first()
    assert item.properties.get("done") is True


def test_reimport_does_not_create_duplicate(db):
    services.import_items(db, ListBoardImportRequest(markdown_text=_MD, source="src"))
    services.import_items(db, ListBoardImportRequest(markdown_text=_MD, source="src"))
    count = db.query(ListBoardItem).count()
    assert count == 1


def test_reimport_updates_source(db):
    services.import_items(db, ListBoardImportRequest(markdown_text=_MD, source="old"))
    services.import_items(db, ListBoardImportRequest(markdown_text=_MD, source="new"))
    item = db.query(ListBoardItem).first()
    assert item.source == "new"
