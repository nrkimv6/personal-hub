from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.auth import create_access_token
from app.database import get_db
from app.models import DismissedDuplicate, EntitySource, Event, InstagramPost
from app.routes.duplicates import router as duplicates_router


pytestmark = pytest.mark.http


@pytest.fixture
def admin_headers():
    token = create_access_token(email="admin@test.com", is_admin=True)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def test_db_session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'event_duplicates_api.db'}",
        connect_args={"check_same_thread": False},
    )
    for table in [
        InstagramPost.__table__,
        Event.__table__,
        EntitySource.__table__,
        DismissedDuplicate.__table__,
    ]:
        table.create(bind=engine, checkfirst=True)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def client(test_db_session):
    def override_get_db():
        yield test_db_session

    test_app = FastAPI()
    test_app.include_router(duplicates_router)
    test_app.dependency_overrides[get_db] = override_get_db
    yield TestClient(test_app)
    test_app.dependency_overrides.clear()


def _event(test_db_session, title: str, **kwargs) -> Event:
    data = {
        "title": title,
        "event_type": "event",
        "status": "active",
        "source_type": "manual",
        "event_start": date.today(),
        "event_end": date.today() + timedelta(days=3),
        "organizer": "API중복브랜드",
        "prizes": ["쿠폰"],
    }
    data.update(kwargs)
    event = Event(**data)
    test_db_session.add(event)
    test_db_session.commit()
    test_db_session.refresh(event)
    return event


def _source(test_db_session, event_id: int, source_id: int) -> None:
    test_db_session.add(
        EntitySource(
            entity_type="event",
            entity_id=event_id,
            source_type="web",
            source_id=source_id,
            source_url=f"https://example.com/{source_id}",
        )
    )
    test_db_session.commit()


def test_candidates_R_returns_candidate_schema(client, test_db_session, admin_headers):
    first = _event(test_db_session, "api candidate first")
    second = _event(test_db_session, "api candidate second")

    response = client.get(
        "/api/v1/duplicates/candidates?entity_type=event&min_similarity=0.5&max_similarity=1&limit=20",
        headers=admin_headers,
    )

    assert response.status_code == 200
    items = response.json()
    item = next(row for row in items if {row["entity1_id"], row["entity2_id"]} == {first.id, second.id})
    assert item["entity_type"] == "event"
    assert item["similarity"] >= 0.5
    assert "matched_fields" in item
    assert item["primary"]["id"] in {first.id, second.id}
    assert item["secondary"]["id"] in {first.id, second.id}


def test_preview_R_returns_merge_preview_schema(client, test_db_session, admin_headers):
    primary = _event(test_db_session, "api preview primary")
    secondary = _event(test_db_session, "api preview secondary")
    _source(test_db_session, primary.id, 21)
    _source(test_db_session, secondary.id, 22)

    response = client.get(
        f"/api/v1/duplicates/preview?entity_type=event&primary_id={primary.id}&secondary_id={secondary.id}",
        headers=admin_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["primary_id"] == primary.id
    assert data["secondary_id"] == secondary.id
    assert data["primary_source_count"] == 1
    assert data["secondary_source_count"] == 1
    assert any(field["field"] == "title" for field in data["fields"])


def test_merge_R_returns_merged_id_deleted_id_source_count(client, test_db_session, admin_headers):
    primary = _event(test_db_session, "api merge primary")
    secondary = _event(test_db_session, "api merge secondary")
    _source(test_db_session, primary.id, 31)
    _source(test_db_session, secondary.id, 32)

    response = client.post(
        "/api/v1/duplicates/merge",
        headers=admin_headers,
        json={
            "entity_type": "event",
            "primary_id": primary.id,
            "secondary_id": secondary.id,
            "field_selections": {"title": "secondary"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["merged_id"] == primary.id
    assert data["disabled_id"] == secondary.id
    assert data["source_count"] == 2
    assert data["secondary_status"] == "disabled"
    assert data["updated_fields"] == ["title"]


def test_dismiss_R_prevents_pair_from_candidates(client, test_db_session, admin_headers):
    first = _event(test_db_session, "api dismiss first", organizer="dismiss api")
    second = _event(test_db_session, "api dismiss second", organizer="dismiss api")

    response = client.post(
        "/api/v1/duplicates/dismiss",
        headers=admin_headers,
        json={"entity_type": "event", "entity1_id": second.id, "entity2_id": first.id},
    )
    assert response.status_code == 200

    candidates = client.get(
        "/api/v1/duplicates/candidates?entity_type=event&min_similarity=0.5&max_similarity=1&limit=50",
        headers=admin_headers,
    )
    assert candidates.status_code == 200
    pairs = [{row["entity1_id"], row["entity2_id"]} for row in candidates.json()]
    assert {first.id, second.id} not in pairs


def test_duplicates_E_requires_admin_for_candidate_preview_merge_dismiss(
    client,
    test_db_session,
    mock_external_request,
):
    primary = _event(test_db_session, "api auth primary")
    secondary = _event(test_db_session, "api auth secondary")

    assert client.get("/api/v1/duplicates/candidates").status_code == 401
    assert client.get(
        f"/api/v1/duplicates/preview?primary_id={primary.id}&secondary_id={secondary.id}"
    ).status_code == 401
    assert client.post(
        "/api/v1/duplicates/merge",
        json={"primary_id": primary.id, "secondary_id": secondary.id},
    ).status_code == 401
    assert client.post(
        "/api/v1/duplicates/dismiss",
        json={"entity1_id": primary.id, "entity2_id": secondary.id},
    ).status_code == 401
