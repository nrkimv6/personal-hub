"""Properties patch TC — partial merge, type validation."""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, JSON as SA_JSON
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.modules.list_board.models import ListBoardColumn, ListBoardItem
from app.modules.list_board.schemas import (
    ColumnCreate,
    ItemPropertiesPatch,
    ListBoardImportRequest,
)
from app.modules.list_board import services


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
def setup(db):
    """item 1개 + checkbox/text/select 컬럼 생성."""
    services.import_items(
        db,
        ListBoardImportRequest(
            markdown_text=(
                "| Course | Duration |\n"
                "|--------|----------|\n"
                "| [Course A](https://example.com/a) | 30 minutes |"
            ),
            source="test",
        ),
    )
    item = db.query(ListBoardItem).first()
    services.create_column(db, ColumnCreate(key="done", display_name="완료", column_type="checkbox"))
    services.create_column(db, ColumnCreate(key="memo", display_name="메모", column_type="text"))
    services.create_column(db, ColumnCreate(key="status", display_name="상태", column_type="select", options=["진행중", "완료"]))
    return item


# overwrite-block: partial merge preserves untouched keys

def test_patch_partial_merge_preserves_other_keys(db, setup):
    item = setup
    item.properties = {"done": True, "memo": "keep"}
    db.commit()

    services.patch_item_properties(db, item.id, ItemPropertiesPatch(properties={"memo": "changed"}))
    updated = db.query(ListBoardItem).filter_by(id=item.id).first()
    assert updated.properties["done"] is True
    assert updated.properties["memo"] == "changed"


def test_patch_checkbox_bool_value(db, setup):
    item = setup
    result = services.patch_item_properties(db, item.id, ItemPropertiesPatch(properties={"done": True}))
    assert result.properties["done"] is True


def test_patch_text_string_value(db, setup):
    item = setup
    result = services.patch_item_properties(db, item.id, ItemPropertiesPatch(properties={"memo": "hello"}))
    assert result.properties["memo"] == "hello"


def test_patch_text_null_value(db, setup):
    item = setup
    result = services.patch_item_properties(db, item.id, ItemPropertiesPatch(properties={"memo": None}))
    assert result.properties["memo"] is None


def test_patch_select_valid_option(db, setup):
    item = setup
    result = services.patch_item_properties(db, item.id, ItemPropertiesPatch(properties={"status": "진행중"}))
    assert result.properties["status"] == "진행중"


# type validation errors → 400

def test_patch_checkbox_non_bool_raises_400(db, setup):
    item = setup
    with pytest.raises(HTTPException) as exc:
        services.patch_item_properties(db, item.id, ItemPropertiesPatch(properties={"done": "yes"}))
    assert exc.value.status_code == 400


def test_patch_select_invalid_option_raises_400(db, setup):
    item = setup
    with pytest.raises(HTTPException) as exc:
        services.patch_item_properties(db, item.id, ItemPropertiesPatch(properties={"status": "invalid"}))
    assert exc.value.status_code == 400


def test_patch_unknown_key_raises_400(db, setup):
    item = setup
    with pytest.raises(HTTPException) as exc:
        services.patch_item_properties(db, item.id, ItemPropertiesPatch(properties={"ghost": "x"}))
    assert exc.value.status_code == 400


def test_patch_item_not_found_raises_404(db):
    _patch_jsonb()
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    with pytest.raises(HTTPException) as exc:
        services.patch_item_properties(session, 9999, ItemPropertiesPatch(properties={}))
    assert exc.value.status_code == 404
    session.close()
