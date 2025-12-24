"""
Event 서비스 테스트 (RIGHT-BICEP)

RIGHT-BICEP 테스트 원칙:
- Right: 정상 동작 확인
- Boundary: 경계 조건 테스트
- Inverse: 역관계 테스트
- Cross-check: 교차 검증
- Error: 에러 조건 테스트
- Performance: 성능 테스트 (선택적)
"""

import pytest
from datetime import date, timedelta

from app.services.event_service import EventService, detect_url_type
from app.schemas.event import EventCreate, EventUpdate, EventImportFromInstagram
from app.models.event import Event
from app.models.instagram_post import InstagramPost


class TestDetectUrlType:
    """URL 타입 자동 분류 테스트"""

    def test_google_form_patterns(self):
        """Right: 구글 폼 URL 인식"""
        assert detect_url_type("https://forms.gle/abc123") == "google_form"
        assert detect_url_type("https://docs.google.com/forms/d/e/xxx") == "google_form"

    def test_naver_form_patterns(self):
        """Right: 네이버 폼 URL 인식"""
        assert detect_url_type("https://naver.me/abc123") == "naver_form"
        assert detect_url_type("https://form.naver.com/xxx") == "naver_form"
        assert detect_url_type("https://survey.naver.com/xxx") == "naver_form"

    def test_survey_patterns(self):
        """Right: 설문조사 URL 인식"""
        assert detect_url_type("https://www.surveymonkey.com/r/xxx") == "survey"
        assert detect_url_type("https://typeform.com/to/xxx") == "survey"
        assert detect_url_type("https://sthp.kr/survey/123") == "survey"

    def test_sns_patterns(self):
        """Right: SNS URL 인식"""
        assert detect_url_type("https://instagram.com/p/xxx") == "sns"
        assert detect_url_type("https://twitter.com/xxx") == "sns"
        assert detect_url_type("https://x.com/xxx") == "sns"

    def test_shop_patterns(self):
        """Right: 쇼핑몰 URL 인식"""
        assert detect_url_type("https://example-shop.com") == "shop"
        assert detect_url_type("https://store.example.com") == "shop"
        assert detect_url_type("https://example-mall.co.kr") == "shop"

    def test_other_patterns(self):
        """Right: 기타 URL 처리"""
        assert detect_url_type("https://example.com/event") == "other"
        assert detect_url_type("https://imbc.com/2025ent") == "other"

    def test_empty_url(self):
        """Boundary: 빈 URL 처리"""
        assert detect_url_type("") == "other"
        assert detect_url_type(None) == "other"

    def test_case_insensitive(self):
        """Right: 대소문자 구분 안함"""
        assert detect_url_type("https://FORMS.GLE/abc") == "google_form"
        assert detect_url_type("https://NAVER.ME/abc") == "naver_form"


class TestEventServiceCRUD:
    """Event CRUD 테스트"""

    @pytest.fixture
    def event_service(self):
        return EventService()

    @pytest.fixture
    def sample_event_data(self):
        return EventCreate(
            title="테스트 이벤트",
            event_type="event",
            event_url="https://forms.gle/test123",
            event_start=date.today(),
            event_end=date.today() + timedelta(days=7),
            organizer="테스트 주최사",
            summary="테스트 이벤트 설명",
            prizes=["경품1", "경품2"],
            winner_count=10,
            source_type="manual",
        )

    def test_create_event(self, test_db_session, event_service, sample_event_data):
        """Right: 이벤트 생성"""
        event = event_service.create_event(test_db_session, sample_event_data)

        assert event.id is not None
        assert event.title == "테스트 이벤트"
        assert event.event_type == "event"
        assert event.url_type == "google_form"  # 자동 분류
        assert event.status == "active"
        assert event.is_bookmarked is False
        assert event.is_participated is False

    def test_create_event_auto_url_type(self, test_db_session, event_service):
        """Right: URL 타입 자동 분류"""
        data = EventCreate(
            title="네이버 폼 이벤트",
            event_url="https://naver.me/test123",
        )
        event = event_service.create_event(test_db_session, data)

        assert event.url_type == "naver_form"

    def test_create_event_custom_url_type(self, test_db_session, event_service):
        """Right: 수동 URL 타입 지정"""
        data = EventCreate(
            title="커스텀 타입 이벤트",
            event_url="https://example.com/event",
            url_type="shop",  # 수동 지정
        )
        event = event_service.create_event(test_db_session, data)

        assert event.url_type == "shop"

    def test_get_event(self, test_db_session, event_service, sample_event_data):
        """Right: 이벤트 조회"""
        created = event_service.create_event(test_db_session, sample_event_data)
        fetched = event_service.get_event(test_db_session, created.id)

        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.title == created.title

    def test_get_event_not_found(self, test_db_session, event_service):
        """Error: 존재하지 않는 이벤트 조회"""
        result = event_service.get_event(test_db_session, 99999)
        assert result is None

    def test_update_event(self, test_db_session, event_service, sample_event_data):
        """Right: 이벤트 수정"""
        created = event_service.create_event(test_db_session, sample_event_data)

        update_data = EventUpdate(
            title="수정된 제목",
            status="ended",
        )
        updated = event_service.update_event(test_db_session, created.id, update_data)

        assert updated.title == "수정된 제목"
        assert updated.status == "ended"
        assert updated.organizer == "테스트 주최사"  # 변경 안됨

    def test_update_event_url_type_recalculation(self, test_db_session, event_service, sample_event_data):
        """Right: URL 변경 시 url_type 재계산"""
        created = event_service.create_event(test_db_session, sample_event_data)
        assert created.url_type == "google_form"

        update_data = EventUpdate(event_url="https://naver.me/new123")
        updated = event_service.update_event(test_db_session, created.id, update_data)

        assert updated.url_type == "naver_form"

    def test_update_event_not_found(self, test_db_session, event_service):
        """Error: 존재하지 않는 이벤트 수정"""
        update_data = EventUpdate(title="수정")
        result = event_service.update_event(test_db_session, 99999, update_data)
        assert result is None

    def test_delete_event(self, test_db_session, event_service, sample_event_data):
        """Right: 이벤트 삭제"""
        created = event_service.create_event(test_db_session, sample_event_data)
        result = event_service.delete_event(test_db_session, created.id)

        assert result is True

        # Inverse: 삭제 후 조회 불가
        fetched = event_service.get_event(test_db_session, created.id)
        assert fetched is None

    def test_delete_event_not_found(self, test_db_session, event_service):
        """Error: 존재하지 않는 이벤트 삭제"""
        result = event_service.delete_event(test_db_session, 99999)
        assert result is False


class TestEventServiceToggle:
    """북마크/참여 토글 테스트"""

    @pytest.fixture
    def event_service(self):
        return EventService()

    @pytest.fixture
    def created_event(self, test_db_session, event_service):
        data = EventCreate(title="토글 테스트 이벤트")
        return event_service.create_event(test_db_session, data)

    def test_toggle_bookmark(self, test_db_session, event_service, created_event):
        """Right: 북마크 토글"""
        assert created_event.is_bookmarked is False

        # 토글 ON
        toggled = event_service.toggle_bookmark(test_db_session, created_event.id)
        assert toggled.is_bookmarked is True

        # 토글 OFF
        toggled = event_service.toggle_bookmark(test_db_session, created_event.id)
        assert toggled.is_bookmarked is False

    def test_toggle_participated(self, test_db_session, event_service, created_event):
        """Right: 참여 완료 토글"""
        assert created_event.is_participated is False

        # 토글 ON
        toggled = event_service.toggle_participated(test_db_session, created_event.id)
        assert toggled.is_participated is True

        # 토글 OFF
        toggled = event_service.toggle_participated(test_db_session, created_event.id)
        assert toggled.is_participated is False

    def test_toggle_bookmark_not_found(self, test_db_session, event_service):
        """Error: 존재하지 않는 이벤트 북마크 토글"""
        result = event_service.toggle_bookmark(test_db_session, 99999)
        assert result is None


class TestEventServiceFilter:
    """이벤트 필터링 테스트"""

    @pytest.fixture
    def event_service(self):
        return EventService()

    @pytest.fixture
    def sample_events(self, test_db_session, event_service):
        """테스트용 이벤트 여러 개 생성"""
        events = []
        today = date.today()

        # 진행 중 이벤트
        events.append(event_service.create_event(test_db_session, EventCreate(
            title="진행 중 이벤트",
            event_type="event",
            event_start=today - timedelta(days=3),
            event_end=today + timedelta(days=7),
        )))

        # 예정 팝업
        events.append(event_service.create_event(test_db_session, EventCreate(
            title="예정 팝업",
            event_type="popup",
            event_start=today + timedelta(days=5),
            event_end=today + timedelta(days=15),
            location_venue="테스트 장소",
        )))

        # 종료된 이벤트
        events.append(event_service.create_event(test_db_session, EventCreate(
            title="종료된 이벤트",
            event_type="event",
            event_start=today - timedelta(days=20),
            event_end=today - timedelta(days=5),
        )))

        # 북마크된 이벤트
        events.append(event_service.create_event(test_db_session, EventCreate(
            title="북마크 이벤트",
            event_type="ambassador",
        )))
        event_service.toggle_bookmark(test_db_session, events[-1].id)

        return events

    def test_filter_by_event_type(self, test_db_session, event_service, sample_events):
        """Right: 이벤트 유형 필터"""
        result = event_service.get_events(test_db_session, event_type="popup")
        assert result.total >= 1
        for item in result.items:
            assert item.event_type == "popup"

    def test_filter_by_event_status_ongoing(self, test_db_session, event_service, sample_events):
        """Right: 진행 중 상태 필터"""
        result = event_service.get_events(test_db_session, event_status="ongoing")
        for item in result.items:
            assert item.event_status == "ongoing"

    def test_filter_by_event_status_upcoming(self, test_db_session, event_service, sample_events):
        """Right: 예정 상태 필터"""
        result = event_service.get_events(test_db_session, event_status="upcoming")
        for item in result.items:
            assert item.event_status == "upcoming"

    def test_filter_by_event_status_ended(self, test_db_session, event_service, sample_events):
        """Right: 종료 상태 필터"""
        result = event_service.get_events(test_db_session, event_status="ended")
        for item in result.items:
            assert item.event_status == "ended"

    def test_filter_by_is_bookmarked(self, test_db_session, event_service, sample_events):
        """Right: 북마크 필터"""
        result = event_service.get_events(test_db_session, is_bookmarked=True)
        assert result.total >= 1
        for item in result.items:
            assert item.is_bookmarked is True

    def test_sort_by_event_end(self, test_db_session, event_service, sample_events):
        """Right: 종료일 기준 정렬"""
        result = event_service.get_events(test_db_session, sort_by="event_end", sort_order="asc")

        # event_end가 있는 항목들이 앞에 오고, NULL은 뒤로
        non_null_items = [i for i in result.items if i.event_end is not None]
        for i in range(len(non_null_items) - 1):
            assert non_null_items[i].event_end <= non_null_items[i + 1].event_end

    def test_pagination(self, test_db_session, event_service, sample_events):
        """Right: 페이지네이션"""
        result = event_service.get_events(test_db_session, page=1, page_size=2)

        assert len(result.items) <= 2
        assert result.page == 1
        assert result.page_size == 2
        assert result.total >= 4  # sample_events에서 4개 생성


class TestEventServiceImportFromInstagram:
    """Instagram에서 이벤트 가져오기 테스트"""

    @pytest.fixture
    def event_service(self):
        return EventService()

    @pytest.fixture
    def instagram_post(self, test_db_session, request):
        """테스트용 Instagram 게시물 생성 (테스트별 고유 ID)"""
        import uuid
        unique_id = f"test_post_{uuid.uuid4().hex[:8]}"
        post = InstagramPost(
            post_id=unique_id,
            account="test_account",
            url=f"https://instagram.com/p/{unique_id}",
            caption="테스트 게시물",
        )
        test_db_session.add(post)
        test_db_session.commit()
        test_db_session.refresh(post)
        return post

    def test_import_from_instagram(self, test_db_session, event_service, instagram_post):
        """Right: Instagram 게시물에서 이벤트 생성"""
        data = EventImportFromInstagram(instagram_post_id=instagram_post.id)
        event = event_service.import_from_instagram(test_db_session, data)

        assert event is not None
        assert event.title == "test_account의 이벤트"  # llm_* 필드 제거로 기본 제목 사용
        assert event.event_type == "event"
        assert event.source_type == "instagram"
        assert event.source_instagram_post_id == instagram_post.id

    def test_import_with_custom_title(self, test_db_session, event_service, instagram_post):
        """Right: 커스텀 제목으로 가져오기"""
        data = EventImportFromInstagram(
            instagram_post_id=instagram_post.id,
            title="내가 정한 제목",
        )
        event = event_service.import_from_instagram(test_db_session, data)

        assert event.title == "내가 정한 제목"

    def test_import_duplicate_returns_existing(self, test_db_session, event_service, instagram_post):
        """Cross-check: 중복 가져오기 시 기존 이벤트 반환"""
        data = EventImportFromInstagram(instagram_post_id=instagram_post.id)

        first = event_service.import_from_instagram(test_db_session, data)
        second = event_service.import_from_instagram(test_db_session, data)

        assert first.id == second.id

    def test_import_post_not_found(self, test_db_session, event_service):
        """Error: 존재하지 않는 게시물"""
        data = EventImportFromInstagram(instagram_post_id=99999)
        result = event_service.import_from_instagram(test_db_session, data)

        assert result is None


class TestEventStatusCalculation:
    """이벤트 상태 계산 테스트"""

    @pytest.fixture
    def event_service(self):
        return EventService()

    def test_ongoing_status(self, test_db_session, event_service):
        """Right: 진행 중 상태 계산"""
        today = date.today()
        data = EventCreate(
            title="진행 중",
            event_start=today - timedelta(days=3),
            event_end=today + timedelta(days=3),
        )
        event = event_service.create_event(test_db_session, data)

        assert event.event_status == "ongoing"
        assert event.days_remaining == 3

    def test_upcoming_status(self, test_db_session, event_service):
        """Right: 예정 상태 계산"""
        today = date.today()
        data = EventCreate(
            title="예정",
            event_start=today + timedelta(days=5),
            event_end=today + timedelta(days=10),
        )
        event = event_service.create_event(test_db_session, data)

        assert event.event_status == "upcoming"
        assert event.days_remaining == 10

    def test_ended_status(self, test_db_session, event_service):
        """Right: 종료 상태 계산"""
        today = date.today()
        data = EventCreate(
            title="종료됨",
            event_start=today - timedelta(days=10),
            event_end=today - timedelta(days=3),
        )
        event = event_service.create_event(test_db_session, data)

        assert event.event_status == "ended"
        assert event.days_remaining == -3

    def test_no_dates_ongoing(self, test_db_session, event_service):
        """Boundary: 날짜 없으면 ongoing"""
        data = EventCreate(title="날짜 없음")
        event = event_service.create_event(test_db_session, data)

        assert event.event_status == "ongoing"
        assert event.days_remaining is None


class TestDuplicateUrlCheck:
    """URL 중복 확인 테스트"""

    @pytest.fixture
    def event_service(self):
        return EventService()

    def test_check_duplicate_url(self, test_db_session, event_service):
        """Right: 중복 URL 확인"""
        data = EventCreate(
            title="이벤트1",
            event_url="https://forms.gle/duplicate123",
        )
        event_service.create_event(test_db_session, data)

        # 중복 확인
        duplicate = event_service.check_duplicate_url(
            test_db_session, "https://forms.gle/duplicate123"
        )
        assert duplicate is not None

    def test_check_duplicate_url_not_found(self, test_db_session, event_service):
        """Right: 중복 없음 확인"""
        result = event_service.check_duplicate_url(
            test_db_session, "https://forms.gle/unique123"
        )
        assert result is None

    def test_check_duplicate_url_exclude_id(self, test_db_session, event_service):
        """Right: 특정 ID 제외하고 중복 확인"""
        data = EventCreate(
            title="이벤트",
            event_url="https://forms.gle/test456",
        )
        created = event_service.create_event(test_db_session, data)

        # 자신 제외하고 확인 -> 중복 없음
        result = event_service.check_duplicate_url(
            test_db_session, "https://forms.gle/test456", exclude_id=created.id
        )
        assert result is None
