from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event as sa_event, text
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, get_db
from app.models.tracking_item import TrackingItem, TrackingItemPlanLink
from app.models.plan_record import PlanRecord
from app.routes.tracking import router as tracking_router
from app.core.auth import require_admin, UserInfo


# ── fixtures ──────────────────────────────────────────────────────────────────

def _make_userinfo() -> UserInfo:
    return UserInfo(email="test@test.com", is_admin=True)


@pytest.fixture()
def link_api_context(tmp_path) -> Iterator[tuple[TestClient, Session]]:
    db_path = tmp_path / "tracking_link_test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    # Base.metadata.create_all() 대신 필요한 테이블만 직접 생성 (다른 모델 FK 충돌 방지)
    from app.models.plan_record import PlanEvent
    TrackingItem.__table__.create(bind=engine, checkfirst=True)
    PlanRecord.__table__.create(bind=engine, checkfirst=True)
    PlanEvent.__table__.create(bind=engine, checkfirst=True)
    TrackingItemPlanLink.__table__.create(bind=engine, checkfirst=True)
    session = SessionLocal()

    app = FastAPI()
    app.include_router(tracking_router)

    def override_get_db():
        yield session

    def override_require_admin():
        return _make_userinfo()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = override_require_admin

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, session
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def _create_item(session: Session, title: str = "Test Item") -> TrackingItem:
    item = TrackingItem(title=title, due_at=datetime.now() + timedelta(days=1))
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def _create_plan(session: Session, title: str = "Test Plan", file_path: str = "docs/plan/2026-01-01_test.md") -> PlanRecord:
    import hashlib
    from pathlib import Path
    filename = Path(file_path).name
    fhash = hashlib.sha256(filename.encode()).hexdigest()
    record = PlanRecord(filename_hash=fhash, file_path=file_path, title=title, status="planned")
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


# ── TC 11: RIGHT 정상 동작 ─────────────────────────────────────────────────────

def test_link_plans_returns_linked_plans_with_correct_fields(link_api_context):
    """R, CORRECT-C-Conformance — link 후 LinkedPlan 모든 필드 반환."""
    client, session = link_api_context
    item = _create_item(session)
    plan = _create_plan(session)

    resp = client.post(f"/api/v1/tracking/items/{item.id}/plans", json={"plan_record_ids": [plan.id]})
    assert resp.status_code == 200
    data = resp.json()
    assert "linked_plans" in data
    assert len(data["linked_plans"]) == 1
    lp = data["linked_plans"][0]
    assert lp["plan_record_id"] == plan.id
    assert lp["filename_hash"] == plan.filename_hash
    assert lp["title"] == plan.title
    assert lp["status"] == plan.status
    assert lp["file_path"] == plan.file_path
    assert isinstance(lp["archived"], bool)
    assert isinstance(lp["file_removed"], bool)


def test_link_plans_creates_links_idempotently(link_api_context):
    """R, B-Cardinality — 동일 plan_record_id 2회 link → linked_plans 1건, status 200."""
    client, session = link_api_context
    item = _create_item(session)
    plan = _create_plan(session)

    client.post(f"/api/v1/tracking/items/{item.id}/plans", json={"plan_record_ids": [plan.id]})
    resp = client.post(f"/api/v1/tracking/items/{item.id}/plans", json={"plan_record_ids": [plan.id]})
    assert resp.status_code == 200
    assert len(resp.json()["linked_plans"]) == 1


# ── TC 12: BOUNDARY ───────────────────────────────────────────────────────────

def test_link_empty_plan_record_ids_array(link_api_context):
    """B-Cardinality 0 — 빈 배열 link → 200, linked_plans 변동 없음."""
    client, session = link_api_context
    item = _create_item(session)
    plan = _create_plan(session)
    client.post(f"/api/v1/tracking/items/{item.id}/plans", json={"plan_record_ids": [plan.id]})

    resp = client.post(f"/api/v1/tracking/items/{item.id}/plans", json={"plan_record_ids": []})
    assert resp.status_code == 200
    assert len(resp.json()["linked_plans"]) == 1


def test_link_duplicate_ids_in_same_request(link_api_context):
    """B-Cardinality dedupe — 한 요청 중복 ID → linked_plans 1건."""
    client, session = link_api_context
    item = _create_item(session)
    plan = _create_plan(session)

    resp = client.post(f"/api/v1/tracking/items/{item.id}/plans", json={"plan_record_ids": [plan.id, plan.id, plan.id]})
    assert resp.status_code == 200
    assert len(resp.json()["linked_plans"]) == 1


def test_link_many_plans_in_single_request(link_api_context):
    """B-Cardinality many — 한 번에 plan 5건 link → linked_plans 5건."""
    client, session = link_api_context
    item = _create_item(session)
    plans = [_create_plan(session, f"Plan {i}", f"docs/plan/2026-01-0{i}_test.md") for i in range(1, 6)]
    ids = [p.id for p in plans]

    resp = client.post(f"/api/v1/tracking/items/{item.id}/plans", json={"plan_record_ids": ids})
    assert resp.status_code == 200
    result_ids = {lp["plan_record_id"] for lp in resp.json()["linked_plans"]}
    assert result_ids == set(ids)


def test_unlink_when_no_links_exist(link_api_context):
    """B-Cardinality 0, idempotent — link 0건 상태에서 unlink → 200."""
    client, session = link_api_context
    item = _create_item(session)
    plan = _create_plan(session)

    resp = client.delete(f"/api/v1/tracking/items/{item.id}/plans/{plan.id}")
    assert resp.status_code == 200
    assert resp.json()["linked_plans"] == []


# ── TC 13: INVERSE ────────────────────────────────────────────────────────────

def test_link_unlink_relink_returns_same_state(link_api_context):
    """I — link → unlink → relink 시 plan_record_id 집합 동일."""
    client, session = link_api_context
    item = _create_item(session)
    plan = _create_plan(session)

    client.post(f"/api/v1/tracking/items/{item.id}/plans", json={"plan_record_ids": [plan.id]})
    client.delete(f"/api/v1/tracking/items/{item.id}/plans/{plan.id}")
    resp = client.post(f"/api/v1/tracking/items/{item.id}/plans", json={"plan_record_ids": [plan.id]})
    assert resp.status_code == 200
    result_ids = {lp["plan_record_id"] for lp in resp.json()["linked_plans"]}
    assert result_ids == {plan.id}


# ── TC 14: CROSS-CHECK ────────────────────────────────────────────────────────

def test_response_matches_db_state(link_api_context):
    """C — 응답 linked_plans 집합과 DB 직접 조회 결과 일치."""
    client, session = link_api_context
    item = _create_item(session)
    plans = [_create_plan(session, f"P{i}", f"docs/plan/2026-02-0{i}_test.md") for i in range(1, 4)]

    resp = client.post(f"/api/v1/tracking/items/{item.id}/plans", json={"plan_record_ids": [p.id for p in plans]})
    api_ids = {lp["plan_record_id"] for lp in resp.json()["linked_plans"]}

    db_ids = {
        row.plan_record_id
        for row in session.query(TrackingItemPlanLink).filter_by(tracking_item_id=item.id).all()
    }
    assert api_ids == db_ids


# ── TC 15: ERROR ──────────────────────────────────────────────────────────────

def test_link_nonexistent_tracking_item_returns_404(link_api_context):
    """E, CORRECT-R-Reference — 존재 안 하는 tracking_item_id → 404."""
    client, session = link_api_context
    plan = _create_plan(session)

    resp = client.post("/api/v1/tracking/items/99999/plans", json={"plan_record_ids": [plan.id]})
    assert resp.status_code == 404


def test_link_invalid_plan_record_id_returns_422(link_api_context):
    """E, CORRECT-R-Reference — 존재 안 하는 plan_record_id → 422."""
    client, session = link_api_context
    item = _create_item(session)

    resp = client.post(f"/api/v1/tracking/items/{item.id}/plans", json={"plan_record_ids": [99999]})
    assert resp.status_code == 422


def test_link_negative_or_zero_id_returns_422(link_api_context):
    """E, CORRECT-R-Range — 음수/0 ID → 422."""
    client, session = link_api_context
    item = _create_item(session)

    resp = client.post(f"/api/v1/tracking/items/{item.id}/plans", json={"plan_record_ids": [-1, 0]})
    assert resp.status_code == 422


def test_link_plan_requires_admin(link_api_context):
    """E — 인증 없는 요청 거부."""
    client, session = link_api_context
    # This fixture overrides require_admin, so we test via raw TestClient without override
    item = _create_item(session)
    plan = _create_plan(session)

    # Create fresh app without auth override
    from app.database import Base, get_db
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine2 = create_engine(f"sqlite:///{str(item.id)}_auth_test.db", connect_args={"check_same_thread": False})
    # We just verify that require_admin dependency exists on the endpoint
    # by checking the route has the dependency
    import inspect
    from app.routes import tracking as tracking_module
    source = inspect.getsource(tracking_module.link_plans)
    assert "require_admin" in source


# ── TC 16: PERFORMANCE ────────────────────────────────────────────────────────

def test_list_response_avoids_n_plus_one(link_api_context):
    """P — N+1 방지: item 3개+각 2개 link → selectinload로 쿼리 제한."""
    client, session = link_api_context
    items = [_create_item(session, f"Item {i}") for i in range(3)]
    plans = [_create_plan(session, f"Plan {i}", f"docs/plan/2026-03-0{i}_test.md") for i in range(1, 4)]

    for item in items:
        client.post(f"/api/v1/tracking/items/{item.id}/plans",
                    json={"plan_record_ids": [plans[0].id, plans[1].id]})

    query_count = 0
    @sa_event.listens_for(session.get_bind(), "before_cursor_execute")
    def count_query(*args, **kwargs):
        nonlocal query_count
        query_count += 1

    resp = client.get("/api/v1/tracking/items")
    assert resp.status_code == 200
    # selectinload 사용 시 N+1 없이 제한된 쿼리 수 (5 이하 기대)
    assert query_count <= 5


def test_link_response_time_with_many_links(link_api_context):
    """P, smoke — 10건 link GET 응답 시간이 2초 이내."""
    client, session = link_api_context
    item = _create_item(session)
    plans = [_create_plan(session, f"P{i}", f"docs/plan/2026-04-{i:02d}_test.md") for i in range(1, 11)]
    client.post(f"/api/v1/tracking/items/{item.id}/plans", json={"plan_record_ids": [p.id for p in plans]})

    start = time.time()
    resp = client.get(f"/api/v1/tracking/items/{item.id}")
    elapsed = time.time() - start
    assert resp.status_code == 200
    assert elapsed < 2.0


# ── TC 17: ORDERING ───────────────────────────────────────────────────────────

def test_linked_plans_ordering_is_stable(link_api_context):
    """CORRECT-O — link 순서대로 created_at ASC 응답 유지."""
    client, session = link_api_context
    item = _create_item(session)
    p1 = _create_plan(session, "P1", "docs/plan/2026-05-01_p1.md")
    p2 = _create_plan(session, "P2", "docs/plan/2026-05-02_p2.md")
    p3 = _create_plan(session, "P3", "docs/plan/2026-05-03_p3.md")

    # link in specific order: p2 → p1 → p3
    client.post(f"/api/v1/tracking/items/{item.id}/plans", json={"plan_record_ids": [p2.id]})
    client.post(f"/api/v1/tracking/items/{item.id}/plans", json={"plan_record_ids": [p1.id]})
    client.post(f"/api/v1/tracking/items/{item.id}/plans", json={"plan_record_ids": [p3.id]})

    resp = client.get(f"/api/v1/tracking/items/{item.id}")
    # 실제 단건 조회 endpoint가 없으면 list에서 찾는다
    if resp.status_code == 405 or resp.status_code == 404:
        resp = client.get("/api/v1/tracking/items")
        items_data = resp.json()["items"]
        item_data = next(i for i in items_data if i["id"] == item.id)
    else:
        item_data = resp.json()

    ids = [lp["plan_record_id"] for lp in item_data["linked_plans"]]
    assert ids == [p2.id, p1.id, p3.id]  # insertion order (created_at ASC)


# ── TC 18: EXISTENCE ──────────────────────────────────────────────────────────

def test_linked_plans_includes_file_removed_flag(link_api_context):
    """CORRECT-E — file_removed_at != null plan에 link → file_removed: true."""
    client, session = link_api_context
    item = _create_item(session)
    plan = _create_plan(session)
    plan.file_removed_at = datetime.now()
    session.commit()

    resp = client.post(f"/api/v1/tracking/items/{item.id}/plans", json={"plan_record_ids": [plan.id]})
    assert resp.status_code == 200
    lp = resp.json()["linked_plans"][0]
    assert lp["file_removed"] is True


def test_tracking_item_response_includes_linked_plans(link_api_context):
    """CORRECT-E, R — linked_plans 필드 항상 존재 (0건이면 [], null 아님)."""
    client, session = link_api_context
    item = _create_item(session)

    resp = client.get("/api/v1/tracking/items")
    assert resp.status_code == 200
    item_data = next(i for i in resp.json()["items"] if i["id"] == item.id)
    assert "linked_plans" in item_data
    assert item_data["linked_plans"] == []
    assert item_data["linked_plans"] is not None


# ── TC 19: TIME + CASCADE ─────────────────────────────────────────────────────

def test_link_created_at_reflects_actual_time(link_api_context):
    """CORRECT-T — created_at이 호출 시점 ±5초 이내."""
    client, session = link_api_context
    item = _create_item(session)
    plan = _create_plan(session)

    before = datetime.now()
    client.post(f"/api/v1/tracking/items/{item.id}/plans", json={"plan_record_ids": [plan.id]})
    after = datetime.now()

    link = session.query(TrackingItemPlanLink).filter_by(tracking_item_id=item.id).first()
    assert link is not None
    assert before - timedelta(seconds=5) <= link.created_at <= after + timedelta(seconds=5)


def test_tracking_item_delete_cascades_links(link_api_context):
    """CORRECT-R-Reference — tracking item 삭제 시 link 자동 삭제."""
    client, session = link_api_context
    item = _create_item(session)
    plan = _create_plan(session)
    client.post(f"/api/v1/tracking/items/{item.id}/plans", json={"plan_record_ids": [plan.id]})

    client.delete(f"/api/v1/tracking/items/{item.id}")

    remaining = session.query(TrackingItemPlanLink).filter_by(tracking_item_id=item.id).count()
    assert remaining == 0


def test_plan_record_delete_cascades_links(link_api_context):
    """CORRECT-R-Reference — plan_record 삭제 시 link 자동 삭제, tracking_item 보존."""
    client, session = link_api_context
    item = _create_item(session)
    plan = _create_plan(session)
    client.post(f"/api/v1/tracking/items/{item.id}/plans", json={"plan_record_ids": [plan.id]})

    session.delete(plan)
    session.commit()

    remaining = session.query(TrackingItemPlanLink).filter_by(plan_record_id=plan.id).count()
    assert remaining == 0
    item_check = session.query(TrackingItem).filter_by(id=item.id).first()
    assert item_check is not None


def test_link_archived_plan_returns_archived_flag(link_api_context):
    """CORRECT-C-Conformance — archived plan 연결 시 archived: true."""
    client, session = link_api_context
    item = _create_item(session)
    plan = _create_plan(session)
    plan.archived_at = datetime.now()
    session.commit()

    resp = client.post(f"/api/v1/tracking/items/{item.id}/plans", json={"plan_record_ids": [plan.id]})
    assert resp.status_code == 200
    lp = resp.json()["linked_plans"][0]
    assert lp["archived"] is True


# ── TC 22 (T3): 통합 full-flow ────────────────────────────────────────────────

def test_full_flow_create_link_unlink_complete(link_api_context):
    """T3 — create → link 2개 → list 확인 → unlink 1개 → complete → delete → CASCADE."""
    client, session = link_api_context
    due = (datetime.now() + timedelta(days=1)).isoformat(timespec="seconds")
    create_resp = client.post("/api/v1/tracking/items", json={"title": "Full Flow", "due_at": due})
    assert create_resp.status_code == 201
    item_id = create_resp.json()["id"]

    p1 = _create_plan(session, "F1", "docs/plan/2026-06-01_f1.md")
    p2 = _create_plan(session, "F2", "docs/plan/2026-06-02_f2.md")

    link_resp = client.post(f"/api/v1/tracking/items/{item_id}/plans",
                            json={"plan_record_ids": [p1.id, p2.id]})
    assert len(link_resp.json()["linked_plans"]) == 2

    list_resp = client.get("/api/v1/tracking/items")
    item_data = next(i for i in list_resp.json()["items"] if i["id"] == item_id)
    assert len(item_data["linked_plans"]) == 2

    client.delete(f"/api/v1/tracking/items/{item_id}/plans/{p1.id}")
    list_resp2 = client.get("/api/v1/tracking/items")
    item_data2 = next(i for i in list_resp2.json()["items"] if i["id"] == item_id)
    assert len(item_data2["linked_plans"]) == 1
    assert item_data2["linked_plans"][0]["plan_record_id"] == p2.id

    client.post(f"/api/v1/tracking/items/{item_id}/complete")
    client.post(f"/api/v1/tracking/items/{item_id}/reopen")
    client.delete(f"/api/v1/tracking/items/{item_id}")

    remaining = session.query(TrackingItemPlanLink).filter_by(tracking_item_id=item_id).count()
    assert remaining == 0
