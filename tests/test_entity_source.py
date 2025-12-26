"""
EntitySource 모델 및 다중 출처 통합 테스트

테스트 범위:
- EntitySource CRUD 테스트
- Event/Popup 새 컬럼 테스트
- 마이그레이션 데이터 검증 테스트
"""
import json
import pytest
from datetime import datetime, date
from sqlalchemy import text

from app.models import EntitySource, Event, Popup, InstagramPost


class TestEntitySourceModel:
    """EntitySource 모델 CRUD 테스트"""

    def test_create_entity_source_for_event(self, test_db_session):
        """이벤트에 대한 EntitySource 생성 테스트"""
        # Given: 이벤트 생성
        event = Event(
            title="테스트 이벤트",
            event_type="event",
            source_type="instagram",
        )
        test_db_session.add(event)
        test_db_session.flush()

        # When: EntitySource 생성
        source = EntitySource(
            entity_type="event",
            entity_id=event.id,
            source_type="instagram",
            source_id=123,
            source_url="https://instagram.com/p/abc123",
            source_account="@test_account",
            priority=50,
            is_primary=1,
        )
        test_db_session.add(source)
        test_db_session.flush()

        # Then: 조회 확인
        saved = test_db_session.query(EntitySource).filter(
            EntitySource.id == source.id
        ).first()

        assert saved is not None
        assert saved.entity_type == "event"
        assert saved.entity_id == event.id
        assert saved.source_type == "instagram"
        assert saved.source_url == "https://instagram.com/p/abc123"
        assert saved.is_primary == 1
        assert saved.priority == 50

    def test_create_entity_source_for_popup(self, test_db_session):
        """팝업에 대한 EntitySource 생성 테스트"""
        # Given: 팝업 생성
        popup = Popup(
            title="테스트 팝업",
            source_type="instagram",
        )
        test_db_session.add(popup)
        test_db_session.flush()

        # When: EntitySource 생성
        source = EntitySource(
            entity_type="popup",
            entity_id=popup.id,
            source_type="web",
            source_url="https://popupplay.co.kr/popup/123",
            priority=80,
            is_primary=1,
        )
        test_db_session.add(source)
        test_db_session.flush()

        # Then: 조회 확인
        saved = test_db_session.query(EntitySource).filter(
            EntitySource.entity_type == "popup",
            EntitySource.entity_id == popup.id,
        ).first()

        assert saved is not None
        assert saved.source_type == "web"
        assert saved.priority == 80

    def test_multiple_sources_for_one_entity(self, test_db_session):
        """하나의 엔티티에 여러 출처 연결 테스트"""
        # Given: 이벤트 생성
        event = Event(
            title="다중 출처 이벤트",
            event_type="event",
            source_type="instagram",
        )
        test_db_session.add(event)
        test_db_session.flush()

        # When: 여러 EntitySource 생성
        sources = [
            EntitySource(
                entity_type="event",
                entity_id=event.id,
                source_type="instagram",
                source_id=1,
                source_url="https://instagram.com/p/abc",
                is_primary=1,
                priority=50,
            ),
            EntitySource(
                entity_type="event",
                entity_id=event.id,
                source_type="web",
                source_id=1,
                source_url="https://forms.google.com/xxx",
                is_primary=0,
                priority=75,
            ),
            EntitySource(
                entity_type="event",
                entity_id=event.id,
                source_type="manual",
                source_id=None,
                is_primary=0,
                priority=20,
            ),
        ]
        for s in sources:
            test_db_session.add(s)
        test_db_session.flush()

        # Then: 모든 출처 조회
        saved_sources = test_db_session.query(EntitySource).filter(
            EntitySource.entity_type == "event",
            EntitySource.entity_id == event.id,
        ).all()

        assert len(saved_sources) == 3

        # 대표 출처 확인
        primary = [s for s in saved_sources if s.is_primary == 1]
        assert len(primary) == 1
        assert primary[0].source_type == "instagram"

    def test_unique_constraint(self, test_db_session):
        """중복 출처 제약조건 테스트"""
        # Given: 이벤트와 출처 생성
        event = Event(
            title="중복 테스트",
            event_type="event",
            source_type="instagram",
        )
        test_db_session.add(event)
        test_db_session.flush()

        source1 = EntitySource(
            entity_type="event",
            entity_id=event.id,
            source_type="instagram",
            source_id=100,
        )
        test_db_session.add(source1)
        test_db_session.flush()

        # When/Then: 동일한 조합으로 또 생성 시도하면 에러
        source2 = EntitySource(
            entity_type="event",
            entity_id=event.id,
            source_type="instagram",
            source_id=100,
        )
        test_db_session.add(source2)

        with pytest.raises(Exception):  # IntegrityError 등
            test_db_session.flush()

    def test_contributed_fields_json(self, test_db_session):
        """contributed_fields JSON 저장 테스트"""
        # Given
        event = Event(
            title="JSON 테스트",
            event_type="event",
            source_type="instagram",
        )
        test_db_session.add(event)
        test_db_session.flush()

        # When
        fields = ["title", "thumbnail", "dates"]
        source = EntitySource(
            entity_type="event",
            entity_id=event.id,
            source_type="instagram",
            source_id=1,
            contributed_fields=json.dumps(fields),
        )
        test_db_session.add(source)
        test_db_session.flush()

        # Then
        saved = test_db_session.query(EntitySource).filter(
            EntitySource.id == source.id
        ).first()
        loaded_fields = json.loads(saved.contributed_fields)
        assert loaded_fields == ["title", "thumbnail", "dates"]

    def test_extracted_data_json(self, test_db_session):
        """extracted_data JSON 저장 테스트"""
        # Given
        popup = Popup(
            title="추출 데이터 테스트",
            source_type="web",
        )
        test_db_session.add(popup)
        test_db_session.flush()

        # When
        extracted = {
            "title": "브랜드X 팝업스토어",
            "dates": {"start": "2025-01-01", "end": "2025-01-31"},
            "location": {"venue": "더현대 서울", "address": "서울시 영등포구..."},
        }
        source = EntitySource(
            entity_type="popup",
            entity_id=popup.id,
            source_type="web",
            source_id=1,
            extracted_data=json.dumps(extracted, ensure_ascii=False),
        )
        test_db_session.add(source)
        test_db_session.flush()

        # Then
        saved = test_db_session.query(EntitySource).filter(
            EntitySource.id == source.id
        ).first()
        loaded_data = json.loads(saved.extracted_data)
        assert loaded_data["title"] == "브랜드X 팝업스토어"
        assert loaded_data["location"]["venue"] == "더현대 서울"


class TestEventNewColumns:
    """Event 모델 새 컬럼 테스트"""

    def test_event_source_count_default(self, test_db_session):
        """source_count 기본값 테스트"""
        event = Event(
            title="출처 수 테스트",
            event_type="event",
            source_type="manual",
        )
        test_db_session.add(event)
        test_db_session.flush()

        saved = test_db_session.query(Event).filter(Event.id == event.id).first()
        assert saved.source_count == 1

    def test_event_confidence_score_default(self, test_db_session):
        """confidence_score 기본값 테스트"""
        event = Event(
            title="신뢰도 테스트",
            event_type="event",
            source_type="manual",
        )
        test_db_session.add(event)
        test_db_session.flush()

        saved = test_db_session.query(Event).filter(Event.id == event.id).first()
        assert saved.confidence_score == 50

    def test_event_primary_source_id(self, test_db_session):
        """primary_source_id 설정 테스트"""
        # Given: 이벤트 및 출처 생성
        event = Event(
            title="대표 출처 테스트",
            event_type="event",
            source_type="instagram",
        )
        test_db_session.add(event)
        test_db_session.flush()

        source = EntitySource(
            entity_type="event",
            entity_id=event.id,
            source_type="instagram",
            source_id=1,
            is_primary=1,
        )
        test_db_session.add(source)
        test_db_session.flush()

        # When: primary_source_id 설정
        event.primary_source_id = source.id
        event.source_count = 1
        test_db_session.flush()

        # Then
        saved = test_db_session.query(Event).filter(Event.id == event.id).first()
        assert saved.primary_source_id == source.id

    def test_event_merged_from_json(self, test_db_session):
        """merged_from JSON 저장 테스트"""
        event = Event(
            title="병합 테스트",
            event_type="event",
            source_type="manual",
            merged_from=json.dumps([2, 3, 5]),
        )
        test_db_session.add(event)
        test_db_session.flush()

        saved = test_db_session.query(Event).filter(Event.id == event.id).first()
        merged_ids = json.loads(saved.merged_from)
        assert merged_ids == [2, 3, 5]


class TestPopupNewColumns:
    """Popup 모델 새 컬럼 테스트"""

    def test_popup_source_count_default(self, test_db_session):
        """source_count 기본값 테스트"""
        popup = Popup(
            title="출처 수 테스트",
            source_type="manual",
        )
        test_db_session.add(popup)
        test_db_session.flush()

        saved = test_db_session.query(Popup).filter(Popup.id == popup.id).first()
        assert saved.source_count == 1

    def test_popup_confidence_score_default(self, test_db_session):
        """confidence_score 기본값 테스트"""
        popup = Popup(
            title="신뢰도 테스트",
            source_type="manual",
        )
        test_db_session.add(popup)
        test_db_session.flush()

        saved = test_db_session.query(Popup).filter(Popup.id == popup.id).first()
        assert saved.confidence_score == 50

    def test_popup_primary_source_id(self, test_db_session):
        """primary_source_id 설정 테스트"""
        # Given
        popup = Popup(
            title="대표 출처 테스트",
            source_type="web",
        )
        test_db_session.add(popup)
        test_db_session.flush()

        source = EntitySource(
            entity_type="popup",
            entity_id=popup.id,
            source_type="web",
            source_id=1,
            is_primary=1,
        )
        test_db_session.add(source)
        test_db_session.flush()

        # When
        popup.primary_source_id = source.id
        test_db_session.flush()

        # Then
        saved = test_db_session.query(Popup).filter(Popup.id == popup.id).first()
        assert saved.primary_source_id == source.id


class TestMigrationDataIntegrity:
    """마이그레이션 데이터 무결성 테스트"""

    def test_entity_sources_table_exists(self, test_db_session):
        """entity_sources 테이블 존재 확인"""
        result = test_db_session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='entity_sources'")
        ).fetchone()
        assert result is not None

    def test_entity_sources_indexes_exist(self, test_db_session):
        """entity_sources 인덱스 존재 확인"""
        result = test_db_session.execute(
            text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='entity_sources'")
        ).fetchall()
        index_names = [r[0] for r in result]

        # 주요 인덱스 확인
        assert any("entity" in name for name in index_names)
        assert any("source" in name for name in index_names)
        assert any("primary" in name for name in index_names)

    def test_events_new_columns_exist(self, test_db_session):
        """events 테이블 새 컬럼 존재 확인"""
        result = test_db_session.execute(
            text("PRAGMA table_info(events)")
        ).fetchall()
        column_names = [r[1] for r in result]

        assert "source_count" in column_names
        assert "primary_source_id" in column_names
        assert "confidence_score" in column_names
        assert "merged_from" in column_names

    def test_popups_new_columns_exist(self, test_db_session):
        """popups 테이블 새 컬럼 존재 확인"""
        result = test_db_session.execute(
            text("PRAGMA table_info(popups)")
        ).fetchall()
        column_names = [r[1] for r in result]

        assert "source_count" in column_names
        assert "primary_source_id" in column_names
        assert "confidence_score" in column_names
        assert "merged_from" in column_names

    def test_instagram_event_migration(self, test_db_session):
        """Instagram 출처 이벤트의 entity_sources 마이그레이션 테스트"""
        # Given: Instagram 출처 이벤트 생성 (마이그레이션 시뮬레이션)
        post = InstagramPost(
            post_id="test_post_123",
            account="test_account",
            url="https://instagram.com/p/test123",
            caption="테스트 캡션",
        )
        test_db_session.add(post)
        test_db_session.flush()

        event = Event(
            title="Instagram 이벤트",
            event_type="event",
            source_type="instagram",
            source_instagram_post_id=post.id,
            source_instagram_url=post.url,
            source_instagram_account=post.account,
        )
        test_db_session.add(event)
        test_db_session.flush()

        # When: 마이그레이션 SQL 시뮬레이션
        test_db_session.execute(text("""
            INSERT OR IGNORE INTO entity_sources (
                entity_type, entity_id, source_type, source_id,
                source_url, source_account, priority, is_primary
            )
            SELECT
                'event',
                id,
                source_type,
                source_instagram_post_id,
                COALESCE(source_instagram_url, source_url),
                source_instagram_account,
                50,
                1
            FROM events
            WHERE id = :event_id AND source_type IS NOT NULL
        """), {"event_id": event.id})
        test_db_session.flush()

        # Then: entity_sources에 데이터 확인
        source = test_db_session.query(EntitySource).filter(
            EntitySource.entity_type == "event",
            EntitySource.entity_id == event.id,
        ).first()

        assert source is not None
        assert source.source_type == "instagram"
        assert source.source_id == post.id
        assert source.source_url == post.url
        assert source.source_account == post.account
        assert source.is_primary == 1


class TestEntitySourceProperties:
    """EntitySource 모델 프로퍼티 테스트"""

    def test_is_instagram_property(self, test_db_session):
        """is_instagram 프로퍼티 테스트"""
        source = EntitySource(
            entity_type="event",
            entity_id=1,
            source_type="instagram",
        )
        assert source.is_instagram is True
        assert source.is_web is False
        assert source.is_manual is False

    def test_is_web_property(self, test_db_session):
        """is_web 프로퍼티 테스트"""
        source = EntitySource(
            entity_type="popup",
            entity_id=1,
            source_type="web",
        )
        assert source.is_instagram is False
        assert source.is_web is True
        assert source.is_manual is False

    def test_is_manual_property(self, test_db_session):
        """is_manual 프로퍼티 테스트"""
        source = EntitySource(
            entity_type="event",
            entity_id=1,
            source_type="manual",
        )
        assert source.is_instagram is False
        assert source.is_web is False
        assert source.is_manual is True
