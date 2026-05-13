"""T3 통합 TC — SQLAlchemy 실제 세션 기반 upsert/properties 보존 검증."""
import pytest
from sqlalchemy import create_engine, JSON
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.modules.list_board.models import ListBoardItem, ListBoardColumn
from app.modules.list_board.schemas import ListBoardImportRequest
from app.modules.list_board import services


def _patch_jsonb():
    ListBoardItem.__table__.c.properties.type = JSON()
    ListBoardColumn.__table__.c.options.type = JSON()


@pytest.fixture
def db():
    _patch_jsonb()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def test_same_url_double_import_creates_one_row(db):
    """같은 URL을 두 번 import해도 row가 1개만 존재한다."""
    md = (
        "| Course | Duration |\n"
        "|--------|----------|\n"
        "| [Course A](https://example.com/a) | 30 minutes |"
    )
    req = ListBoardImportRequest(markdown_text=md, source="src")
    r1 = services.import_items(db, req)
    r2 = services.import_items(db, req)

    assert r1.created == 1
    assert r2.updated == 1
    count = db.query(ListBoardItem).filter_by(url="https://example.com/a").count()
    assert count == 1


def test_properties_preserved_and_updated_at_refreshed(db):
    """재import 시 properties는 보존되고 updated_at은 갱신된다."""
    md = (
        "| Course | Duration |\n"
        "|--------|----------|\n"
        "| [Course A](https://example.com/a) | 30 minutes |"
    )
    req = ListBoardImportRequest(markdown_text=md, source="src")
    services.import_items(db, req)

    item = db.query(ListBoardItem).filter_by(url="https://example.com/a").first()
    item.properties = {"checked": True}
    db.commit()
    first_updated = item.updated_at

    import time
    time.sleep(0.01)

    services.import_items(db, req)
    db.refresh(item)

    assert item.properties == {"checked": True}
    assert item.updated_at >= first_updated


def test_multiple_urls_all_created_no_duplicates(db):
    """여러 URL을 포함한 표를 import하면 각 URL당 row 1개만 생성된다."""
    md = (
        "| Course | Duration |\n"
        "|--------|----------|\n"
        "| [Course A](https://example.com/a) | 10 minutes |\n"
        "| [Course B](https://example.com/b) | 20 minutes |\n"
        "| [Course C](https://example.com/c) | 30 minutes |"
    )
    req = ListBoardImportRequest(markdown_text=md, source="batch")
    result = services.import_items(db, req)

    assert result.created == 3
    assert result.updated == 0
    total = db.query(ListBoardItem).count()
    assert total == 3
