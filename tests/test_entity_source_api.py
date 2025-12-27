"""
EntitySource API 테스트
"""
import pytest
import os
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from datetime import datetime

from app.main import app
from app.database import get_db
from app.models.base import Base
from app.models.event import Event
from app.models.popup import Popup
from app.models.entity_source import EntitySource


# 테스트용 인메모리 DB 설정 (연결 공유로 격리 보장)
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,  # 연결 공유
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="function")
def db():
    """테스트 DB 세션 (가장 먼저 실행되어 테이블 생성)"""
    # 테스트마다 새로운 테이블 생성
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    session = TestingSessionLocal()
    yield session
    # 에러 상태여도 안전하게 정리
    try:
        session.rollback()
    except Exception:
        pass
    session.close()


@pytest.fixture(scope="function")
def client(db):
    """테스트 클라이언트 생성 (db fixture에 의존)"""
    # 이 테스트에서만 override 적용
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    # 테스트 후 override 해제
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def test_event(db):
    """테스트용 이벤트 생성"""
    event = Event(
        title="테스트 이벤트",
        event_type="event",
        source_type="manual",
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    yield event

    # 테스트 후 정리
    try:
        db.rollback()  # 에러 상태 해제
        db.query(EntitySource).filter(
            EntitySource.entity_type == "event",
            EntitySource.entity_id == event.id
        ).delete()
        db.delete(event)
        db.commit()
    except Exception:
        db.rollback()


@pytest.fixture
def test_popup(db):
    """테스트용 팝업 생성"""
    popup = Popup(
        title="테스트 팝업",
        brand="테스트 브랜드",
        source_type="manual",
    )
    db.add(popup)
    db.commit()
    db.refresh(popup)

    yield popup

    # 테스트 후 정리
    try:
        db.rollback()  # 에러 상태 해제
        db.query(EntitySource).filter(
            EntitySource.entity_type == "popup",
            EntitySource.entity_id == popup.id
        ).delete()
        db.delete(popup)
        db.commit()
    except Exception:
        db.rollback()


class TestEntitySourceAPI:
    """EntitySource API 테스트"""

    def test_get_sources_empty(self, client, test_event):
        """빈 출처 목록 조회"""
        response = client.get(f"/api/v1/events/{test_event.id}/sources")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []
        assert data["entity_type"] == "event"
        assert data["entity_id"] == test_event.id

    def test_add_source_to_event(self, client, test_event):
        """이벤트에 출처 추가"""
        source_data = {
            "source_type": "instagram",
            "source_id": 123,
            "source_url": "https://instagram.com/p/test123",
            "source_account": "@test_account",
            "priority": 80,
            "contributed_fields": ["title", "thumbnail"],
        }

        response = client.post(
            f"/api/v1/events/{test_event.id}/sources",
            json=source_data,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["source_type"] == "instagram"
        assert data["source_url"] == "https://instagram.com/p/test123"
        assert data["is_primary"] == True  # 첫 번째 출처는 자동으로 primary

    def test_add_second_source(self, client, test_event, db):
        """두 번째 출처 추가 (non-primary)"""
        # 첫 번째 출처 추가
        first_source = {
            "source_type": "instagram",
            "source_id": 100,
            "source_url": "https://instagram.com/p/first",
            "priority": 80,
        }
        client.post(f"/api/v1/events/{test_event.id}/sources", json=first_source)

        # 두 번째 출처 추가
        second_source = {
            "source_type": "web",
            "source_id": 200,
            "source_url": "https://example.com/event",
            "priority": 60,
        }
        response = client.post(
            f"/api/v1/events/{test_event.id}/sources",
            json=second_source,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["is_primary"] == False  # 두 번째 출처는 primary 아님

    def test_get_sources_with_items(self, client, test_event, db):
        """출처가 있는 목록 조회"""
        # 출처 추가
        source = EntitySource(
            entity_type="event",
            entity_id=test_event.id,
            source_type="instagram",
            source_id=999,
            source_url="https://instagram.com/p/test999",
            is_primary=1,
            priority=90,
        )
        db.add(source)
        db.commit()

        response = client.get(f"/api/v1/events/{test_event.id}/sources")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1

    def test_set_primary_source(self, client, test_event, db):
        """대표 출처 변경"""
        # 두 개의 출처 추가
        source1 = EntitySource(
            entity_type="event",
            entity_id=test_event.id,
            source_type="instagram",
            source_id=1001,
            is_primary=1,
            priority=80,
        )
        source2 = EntitySource(
            entity_type="event",
            entity_id=test_event.id,
            source_type="web",
            source_id=1002,
            is_primary=0,
            priority=60,
        )
        db.add_all([source1, source2])
        db.commit()
        db.refresh(source2)

        # source2를 primary로 설정
        response = client.put(
            f"/api/v1/events/{test_event.id}/sources/{source2.id}/primary"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_primary"] == True

        # source1이 더 이상 primary가 아닌지 확인
        db.refresh(source1)
        assert source1.is_primary == 0

    def test_remove_source(self, client, test_event, db):
        """출처 제거"""
        source = EntitySource(
            entity_type="event",
            entity_id=test_event.id,
            source_type="manual",
            source_url="https://example.com/manual",
            is_primary=0,
        )
        db.add(source)
        db.commit()
        db.refresh(source)

        response = client.delete(
            f"/api/v1/events/{test_event.id}/sources/{source.id}"
        )
        assert response.status_code == 204

        # 삭제 확인
        deleted = db.query(EntitySource).filter(EntitySource.id == source.id).first()
        assert deleted is None

    def test_remove_nonexistent_source(self, client, test_event):
        """존재하지 않는 출처 제거"""
        response = client.delete(
            f"/api/v1/events/{test_event.id}/sources/99999"
        )
        assert response.status_code == 404

    def test_popup_sources(self, client, test_popup):
        """팝업 출처 관리"""
        # 출처 추가
        source_data = {
            "source_type": "web",
            "source_url": "https://popupplay.com/popup/123",
            "source_account": "팝업플레이",
            "priority": 75,
        }
        response = client.post(
            f"/api/v1/popups/{test_popup.id}/sources",
            json=source_data,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["entity_type"] == "popup"
        assert data["source_type"] == "web"

        # 목록 조회
        response = client.get(f"/api/v1/popups/{test_popup.id}/sources")
        assert response.status_code == 200
        data = response.json()
        assert data["entity_type"] == "popup"
        assert data["total"] >= 1

    def test_update_source(self, client, test_event, db):
        """출처 정보 수정"""
        source = EntitySource(
            entity_type="event",
            entity_id=test_event.id,
            source_type="instagram",
            source_id=2000,
            priority=50,
        )
        db.add(source)
        db.commit()
        db.refresh(source)

        update_data = {
            "priority": 90,
            "contributed_fields": ["title", "prizes", "dates"],
        }
        response = client.patch(
            f"/api/v1/events/{test_event.id}/sources/{source.id}",
            json=update_data,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["priority"] == 90
        assert "title" in data["contributed_fields"]

    def test_duplicate_source_returns_existing(self, client, test_event, db):
        """중복 출처 추가 시 기존 출처 반환"""
        # 먼저 출처 추가
        source = EntitySource(
            entity_type="event",
            entity_id=test_event.id,
            source_type="instagram",
            source_id=3000,
            source_url="https://instagram.com/p/duplicate",
            is_primary=1,
        )
        db.add(source)
        db.commit()
        db.refresh(source)

        # 같은 출처 다시 추가 시도
        duplicate_data = {
            "source_type": "instagram",
            "source_id": 3000,
            "source_url": "https://instagram.com/p/duplicate",
        }
        response = client.post(
            f"/api/v1/events/{test_event.id}/sources",
            json=duplicate_data,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == source.id  # 기존 출처의 ID 반환


class TestEntitySourceServiceIntegration:
    """EntitySourceService 통합 테스트"""

    def test_source_count_updates(self, client, db):
        """source_count 자동 업데이트 확인"""
        # 새 이벤트 생성 (다른 테스트와 격리)
        event = Event(
            title="카운트 테스트 이벤트",
            event_type="event",
            source_type="manual",
        )
        db.add(event)
        db.commit()
        db.refresh(event)

        try:
            # 초기 상태
            initial_count = event.source_count or 0
            assert initial_count == 0 or initial_count == 1  # 기본값

            # 출처 추가
            source_data = {
                "source_type": "instagram",
                "source_id": 4000,
                "source_url": "https://instagram.com/p/count_test",
            }
            response = client.post(
                f"/api/v1/events/{event.id}/sources",
                json=source_data,
            )
            assert response.status_code == 201
            source_id = response.json()["id"]

            # source_count 확인
            db.refresh(event)
            assert event.source_count == 1

            # 출처 제거
            client.delete(f"/api/v1/events/{event.id}/sources/{source_id}")
            db.refresh(event)
            assert event.source_count == 0
        finally:
            # 정리
            db.query(EntitySource).filter(
                EntitySource.entity_type == "event",
                EntitySource.entity_id == event.id
            ).delete()
            db.delete(event)
            db.commit()

    def test_primary_source_id_updates(self, client, test_event, db):
        """primary_source_id 자동 업데이트 확인"""
        # 출처 추가 (자동으로 primary)
        source_data = {
            "source_type": "instagram",
            "source_id": 5000,
        }
        response = client.post(
            f"/api/v1/events/{test_event.id}/sources",
            json=source_data,
        )
        source_id = response.json()["id"]

        # primary_source_id 확인
        db.refresh(test_event)
        assert test_event.primary_source_id == source_id
