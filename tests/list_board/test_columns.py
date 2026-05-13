"""Column CRUD TC — SQLite in-memory."""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, JSON as SA_JSON
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.modules.list_board.models import ListBoardColumn, ListBoardItem
from app.modules.list_board.schemas import ColumnCreate, ColumnUpdate
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


# creator

def test_create_column_returns_response(db):
    req = ColumnCreate(key="memo", display_name="메모", column_type="text")
    col = services.create_column(db, req)
    assert col.id > 0
    assert col.key == "memo"
    assert col.column_type == "text"
    assert col.is_visible is True


def test_create_column_checkbox_with_options_empty(db):
    req = ColumnCreate(key="done", display_name="완료", column_type="checkbox")
    col = services.create_column(db, req)
    assert col.column_type == "checkbox"
    assert col.options == []


def test_create_column_select_stores_options(db):
    req = ColumnCreate(key="status", display_name="상태", column_type="select", options=["진행중", "완료", "보류"])
    col = services.create_column(db, req)
    assert col.options == ["진행중", "완료", "보류"]


def test_create_column_invalid_key_raises(db):
    with pytest.raises(Exception):
        ColumnCreate(key="1bad", display_name="Bad Key", column_type="text")


def test_create_column_duplicate_key_raises_409(db):
    req = ColumnCreate(key="memo", display_name="메모", column_type="text")
    services.create_column(db, req)
    with pytest.raises(HTTPException) as exc:
        services.create_column(db, req)
    assert exc.value.status_code == 409


# preserver / list

def test_list_columns_ordered_by_sort_order(db):
    services.create_column(db, ColumnCreate(key="zzz", display_name="Z", column_type="text", sort_order=10))
    services.create_column(db, ColumnCreate(key="aaa", display_name="A", column_type="text", sort_order=1))
    cols = services.list_columns(db)
    assert len(cols) == 2
    assert cols[0].key == "aaa"
    assert cols[1].key == "zzz"


# update

def test_update_column_display_name(db):
    col = services.create_column(db, ColumnCreate(key="memo", display_name="메모", column_type="text"))
    updated = services.update_column(db, col.id, ColumnUpdate(display_name="노트"))
    assert updated.display_name == "노트"
    assert updated.key == "memo"


def test_update_column_visibility(db):
    col = services.create_column(db, ColumnCreate(key="memo", display_name="메모", column_type="text"))
    updated = services.update_column(db, col.id, ColumnUpdate(is_visible=False))
    assert updated.is_visible is False


def test_update_column_options(db):
    col = services.create_column(db, ColumnCreate(key="st", display_name="상태", column_type="select", options=["A"]))
    updated = services.update_column(db, col.id, ColumnUpdate(options=["A", "B"]))
    assert updated.options == ["A", "B"]


def test_update_column_not_found_raises_404(db):
    with pytest.raises(HTTPException) as exc:
        services.update_column(db, 9999, ColumnUpdate(display_name="X"))
    assert exc.value.status_code == 404


# override / delete

def test_delete_column_removes_from_db(db):
    col = services.create_column(db, ColumnCreate(key="memo", display_name="메모", column_type="text"))
    services.delete_column(db, col.id)
    cols = services.list_columns(db)
    assert len(cols) == 0


def test_delete_column_not_found_raises_404(db):
    with pytest.raises(HTTPException) as exc:
        services.delete_column(db, 9999)
    assert exc.value.status_code == 404
