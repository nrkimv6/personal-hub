from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, get_db
from app.models.tracking_item import TrackingItem
from app.routes.tracking import router as tracking_router
from app.services.tracking_service import calculate_tracking_status


@pytest.fixture()
def tracking_api_context(tmp_path) -> Iterator[tuple[TestClient, Session]]:
    db_path = tmp_path / "tracking_test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()

    app = FastAPI()
    app.include_router(tracking_router)

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, session
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def test_tracking_create_requires_start_or_due_boundary(tracking_api_context):
    client, _session = tracking_api_context

    response = client.post("/api/v1/tracking/items", json={"title": "No date"})

    assert response.status_code == 422


def test_tracking_status_right_start_only_upcoming_then_ready():
    now = datetime(2026, 4, 29, 12, 0, 0)
    future = TrackingItem(title="Future", start_at=now + timedelta(days=1))
    ready = TrackingItem(title="Ready", start_at=now - timedelta(minutes=1))

    assert calculate_tracking_status(future, now) == "upcoming"
    assert calculate_tracking_status(ready, now) == "ready"


def test_tracking_status_right_due_only_ready_then_overdue():
    now = datetime(2026, 4, 29, 12, 0, 0)
    ready = TrackingItem(title="Ready", due_at=now + timedelta(minutes=1))
    overdue = TrackingItem(title="Overdue", due_at=now - timedelta(minutes=1))

    assert calculate_tracking_status(ready, now) == "ready"
    assert calculate_tracking_status(overdue, now) == "overdue"


def test_tracking_crud_complete_reopen_and_delete(tracking_api_context):
    client, _session = tracking_api_context
    due_at = datetime.now() + timedelta(days=1)

    created = client.post(
        "/api/v1/tracking/items",
        json={"title": "Review deploy", "description": "Check it", "due_at": _iso(due_at)},
    )
    assert created.status_code == 201
    item = created.json()
    assert item["title"] == "Review deploy"
    assert item["status"] == "ready"

    item_id = item["id"]
    patched = client.patch(
        f"/api/v1/tracking/items/{item_id}",
        json={"title": "Review deploy updated", "start_at": _iso(datetime.now())},
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "Review deploy updated"

    completed = client.post(f"/api/v1/tracking/items/{item_id}/complete")
    assert completed.status_code == 200
    assert completed.json()["status"] == "done"
    assert completed.json()["completed_at"] is not None

    reopened = client.post(f"/api/v1/tracking/items/{item_id}/reopen")
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "ready"
    assert reopened.json()["completed_at"] is None

    deleted = client.delete(f"/api/v1/tracking/items/{item_id}")
    assert deleted.status_code == 204
    listed = client.get("/api/v1/tracking/items")
    assert listed.status_code == 200
    assert listed.json()["items"] == []


def test_tracking_list_filters_and_sorts(tracking_api_context):
    client, session = tracking_api_context
    now = datetime.now()
    session.add_all(
        [
            TrackingItem(title="Done old", due_at=now - timedelta(days=5), completed_at=now - timedelta(days=2)),
            TrackingItem(title="Upcoming", start_at=now + timedelta(days=3)),
            TrackingItem(title="Ready soon", due_at=now + timedelta(hours=2)),
            TrackingItem(title="Overdue", due_at=now - timedelta(hours=1)),
            TrackingItem(title="Done new", due_at=now - timedelta(days=1), completed_at=now - timedelta(hours=1)),
        ]
    )
    session.commit()

    response = client.get("/api/v1/tracking/items")
    assert response.status_code == 200
    titles = [item["title"] for item in response.json()["items"]]
    assert titles == ["Overdue", "Ready soon", "Upcoming", "Done new", "Done old"]

    no_done = client.get("/api/v1/tracking/items?include_done=false")
    assert [item["title"] for item in no_done.json()["items"]] == ["Overdue", "Ready soon", "Upcoming"]

    overdue = client.get("/api/v1/tracking/items?status=overdue")
    assert [item["title"] for item in overdue.json()["items"]] == ["Overdue"]


def test_tracking_list_includes_nightly_repo_sync_blocker_ready(tracking_api_context):
    client, session = tracking_api_context
    session.add(
        TrackingItem(
            title="Nightly repo sync blocked",
            description="snapshot_key: nightly_repo_sync:block:root_dirty",
            start_at=datetime.now() - timedelta(minutes=1),
        )
    )
    session.commit()

    response = client.get("/api/v1/tracking/items?status=ready")

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "Nightly repo sync blocked"
    assert items[0]["status"] == "ready"
