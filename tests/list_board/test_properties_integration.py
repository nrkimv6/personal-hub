"""properties 통합 TC: column 생성 → item patch → reimport → sort 한 흐름."""
import pytest
from sqlalchemy import create_engine, JSON as SA_JSON
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.modules.list_board.models import ListBoardColumn, ListBoardItem
from app.modules.list_board.schemas import (
    ColumnCreate,
    ColumnUpdate,
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


_MD_A = (
    "| Course | Duration |\n"
    "|--------|----------|\n"
    "| [Alpha](https://a.com) | 10 minutes |"
)
_MD_B = (
    "| Course | Duration |\n"
    "|--------|----------|\n"
    "| [Beta](https://b.com) | 30 minutes |"
)
_MD_G = (
    "| Course | Duration |\n"
    "|--------|----------|\n"
    "| [Gamma](https://g.com) | 90 minutes |"
)


def test_full_flow_column_create_patch_reimport_sort(db):
    """column 생성 → item properties patch → reimport 후 보존 → sort 전체 흐름."""
    # 1. 3개 item import
    services.import_items(db, ListBoardImportRequest(markdown_text=_MD_A, source="s1"))
    services.import_items(db, ListBoardImportRequest(markdown_text=_MD_B, source="s1"))
    services.import_items(db, ListBoardImportRequest(markdown_text=_MD_G, source="s2"))

    # 2. column 2개 생성
    col_done = services.create_column(db, ColumnCreate(key="done", display_name="완료", column_type="checkbox"))
    col_tag = services.create_column(db, ColumnCreate(key="tag", display_name="태그", column_type="select", options=["A", "B", "C"]))

    # 3. creator axis: column이 생성됐고 기본 options가 있음
    cols = services.list_columns(db)
    assert len(cols) == 2
    assert {c.key for c in cols} == {"done", "tag"}

    # 4. item Alpha에 properties patch
    alpha = db.query(ListBoardItem).filter_by(url="https://a.com").first()
    services.patch_item_properties(db, alpha.id, ItemPropertiesPatch(properties={"done": True, "tag": "A"}))

    # 5. item Beta에 partial patch (done만)
    beta = db.query(ListBoardItem).filter_by(url="https://b.com").first()
    services.patch_item_properties(db, beta.id, ItemPropertiesPatch(properties={"done": False}))

    # 6. overwrite-block axis: Alpha의 tag 값이 done patch로 덮이지 않았는지 확인
    db.refresh(alpha)
    assert alpha.properties.get("done") is True
    assert alpha.properties.get("tag") == "A"

    # 7. preserver axis: Alpha reimport 후 custom properties 보존
    services.import_items(db, ListBoardImportRequest(markdown_text=_MD_A, source="s1_updated"))
    db.refresh(alpha)
    assert alpha.properties.get("done") is True
    assert alpha.properties.get("tag") == "A"
    assert alpha.source == "s1_updated"  # system field는 갱신됨

    # 8. no duplicate after reimport
    total = db.query(ListBoardItem).count()
    assert total == 3

    # 9. sort axis: duration asc → Alpha(10) < Beta(30) < Gamma(90)
    result = services.list_items(db, sort_by="duration_minutes", sort_order="asc")
    durations = [i.duration_minutes for i in result.items]
    assert durations == sorted(durations)

    # 10. sort axis: title desc → Gamma > Beta > Alpha
    result = services.list_items(db, sort_by="title", sort_order="desc")
    titles = [i.title for i in result.items]
    assert titles == sorted(titles, reverse=True)

    # 11. column update axis: tag column 옵션 변경
    services.update_column(db, col_tag.id, ColumnUpdate(options=["A", "B", "C", "D"]))
    updated = db.query(ListBoardColumn).filter_by(id=col_tag.id).first()
    assert "D" in updated.options

    # 12. override axis: column 삭제
    services.delete_column(db, col_done.id)
    remaining = services.list_columns(db)
    assert len(remaining) == 1
    assert remaining[0].key == "tag"


def test_sort_after_multiple_imports(db):
    """여러 source에서 import 후 sort가 올바르게 동작."""
    services.import_items(db, ListBoardImportRequest(markdown_text=_MD_G, source="src_g"))
    services.import_items(db, ListBoardImportRequest(markdown_text=_MD_A, source="src_a"))
    services.import_items(db, ListBoardImportRequest(markdown_text=_MD_B, source="src_b"))

    result = services.list_items(db, sort_by="title", sort_order="asc")
    titles = [i.title for i in result.items]
    assert titles == sorted(titles)
    assert result.total == 3


def test_properties_not_leaked_between_items(db):
    """item A의 properties patch가 item B에 영향 없음."""
    services.import_items(db, ListBoardImportRequest(markdown_text=_MD_A, source="s"))
    services.import_items(db, ListBoardImportRequest(markdown_text=_MD_B, source="s"))
    services.create_column(db, ColumnCreate(key="note", display_name="노트", column_type="text"))

    alpha = db.query(ListBoardItem).filter_by(url="https://a.com").first()
    services.patch_item_properties(db, alpha.id, ItemPropertiesPatch(properties={"note": "only alpha"}))

    beta = db.query(ListBoardItem).filter_by(url="https://b.com").first()
    assert beta.properties.get("note") is None
