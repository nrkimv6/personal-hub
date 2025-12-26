"""
중복 감지 서비스 테스트
"""
import pytest
from datetime import date, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.event import Event
from app.models.popup import Popup
from app.services.duplicate_detection_service import (
    DuplicateDetectionService,
    EVENT_DUPLICATE_THRESHOLD,
    POPUP_DUPLICATE_THRESHOLD,
)
from app.utils.similarity import (
    normalize,
    normalize_url,
    dates_overlap,
    jaccard_similarity,
    text_similarity,
    extract_korean_brand,
)


# 테스트용 DB 설정
SQLALCHEMY_DATABASE_URL = "sqlite:///./test_duplicate_detection.db"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="module")
def db():
    """테스트 DB 세션"""
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def service():
    """중복 감지 서비스"""
    return DuplicateDetectionService()


class TestSimilarityUtils:
    """유사도 유틸리티 함수 테스트"""

    def test_normalize_text(self):
        """텍스트 정규화"""
        assert normalize("Hello World") == "helloworld"
        assert normalize("  테스트  ") == "테스트"
        assert normalize("A B C") == "abc"
        assert normalize("") == ""
        assert normalize(None) == ""

    def test_normalize_url(self):
        """URL 정규화"""
        assert normalize_url("https://www.example.com/path/") == "example.com/path"
        assert normalize_url("http://example.com/page?query=1") == "example.com/page"
        assert normalize_url("https://forms.gle/abc123") == "forms.gle/abc123"
        assert normalize_url("") == ""

    def test_dates_overlap(self):
        """날짜 중복 확인"""
        today = date.today()
        tomorrow = today + timedelta(days=1)
        next_week = today + timedelta(days=7)
        two_weeks = today + timedelta(days=14)

        # 겹치는 경우
        assert dates_overlap(today, next_week, tomorrow, two_weeks) == True
        # 겹치지 않는 경우
        assert dates_overlap(today, tomorrow, next_week, two_weeks) == False
        # None 포함
        assert dates_overlap(today, None, tomorrow, next_week) == False

    def test_jaccard_similarity(self):
        """Jaccard 유사도"""
        # 완전 일치
        assert jaccard_similarity(["a", "b", "c"], ["a", "b", "c"]) == 1.0
        # 부분 일치
        assert jaccard_similarity(["a", "b"], ["b", "c"]) == pytest.approx(1/3)
        # 일치 없음
        assert jaccard_similarity(["a", "b"], ["c", "d"]) == 0.0
        # 빈 리스트
        assert jaccard_similarity([], ["a"]) == 0.0

    def test_text_similarity(self):
        """텍스트 유사도"""
        assert text_similarity("hello world", "hello world") == 1.0
        assert text_similarity("hello world", "hello python") > 0
        assert text_similarity("abc", "xyz") == 0.0
        assert text_similarity("", "hello") == 0.0

    def test_extract_korean_brand(self):
        """브랜드명 추출"""
        assert extract_korean_brand("나이키 코리아") == "나이키"
        assert extract_korean_brand("Nike Korea") == "nike"
        assert extract_korean_brand("아디다스 공식 스토어") == "아디다스공식"
        assert extract_korean_brand("") == ""


class TestEventSimilarity:
    """이벤트 유사도 계산 테스트"""

    def test_same_url_is_identical(self, service):
        """같은 URL이면 동일 이벤트"""
        e1 = Event(
            title="이벤트 A",
            event_url="https://forms.gle/abc123",
        )
        e2 = Event(
            title="다른 이벤트",
            event_url="https://forms.gle/abc123",
        )
        similarity = service.calculate_event_similarity(e1, e2)
        assert similarity == 1.0

    def test_same_organizer_same_period(self, service):
        """같은 주최자, 같은 기간"""
        today = date.today()
        next_week = today + timedelta(days=7)

        e1 = Event(
            title="연말 이벤트",
            organizer="브랜드X",
            event_start=today,
            event_end=next_week,
        )
        e2 = Event(
            title="연말 프로모션",
            organizer="브랜드X",
            event_start=today,
            event_end=next_week,
        )
        similarity = service.calculate_event_similarity(e1, e2)
        # 기간(0.25) + 주최자(0.25) + 제목 유사도(일부)
        assert similarity >= 0.5

    def test_similar_prizes(self, service):
        """유사한 경품"""
        e1 = Event(
            title="경품 이벤트",
            prizes='["아이폰 15", "에어팟"]',
        )
        e2 = Event(
            title="경품 행사",
            prizes='["아이폰 15", "갤럭시 버즈"]',
        )
        similarity = service.calculate_event_similarity(e1, e2)
        # 경품 유사도 기여
        assert similarity > 0

    def test_completely_different_events(self, service):
        """완전히 다른 이벤트"""
        e1 = Event(
            title="여름 세일",
            organizer="A사",
            event_start=date(2024, 7, 1),
            event_end=date(2024, 7, 31),
        )
        e2 = Event(
            title="겨울 이벤트",
            organizer="B사",
            event_start=date(2024, 12, 1),
            event_end=date(2024, 12, 31),
        )
        similarity = service.calculate_event_similarity(e1, e2)
        assert similarity < 0.3


class TestPopupSimilarity:
    """팝업 유사도 계산 테스트"""

    def test_same_brand_same_venue(self, service):
        """같은 브랜드, 같은 장소"""
        p1 = Popup(
            title="나이키 팝업",
            brand="나이키",
            venue_name="더현대 서울",
            start_date=date(2024, 12, 1),
            end_date=date(2024, 12, 31),
        )
        p2 = Popup(
            title="Nike Winter Popup",
            brand="나이키",
            venue_name="더현대 서울",
            start_date=date(2024, 12, 15),
            end_date=date(2025, 1, 15),
        )
        similarity = service.calculate_popup_similarity(p1, p2)
        # 브랜드(0.35) + 기간(0.25) + 장소(0.25) = 0.85
        assert similarity >= 0.8

    def test_same_brand_different_venue(self, service):
        """같은 브랜드, 다른 장소"""
        p1 = Popup(
            title="나이키 성수",
            brand="나이키",
            venue_name="성수 플래그십",
        )
        p2 = Popup(
            title="나이키 강남",
            brand="나이키",
            venue_name="강남 플래그십",
        )
        similarity = service.calculate_popup_similarity(p1, p2)
        # 같은 브랜드지만 다른 장소 = 다른 팝업
        assert similarity < POPUP_DUPLICATE_THRESHOLD

    def test_different_brands(self, service):
        """다른 브랜드"""
        p1 = Popup(
            title="아디다스 팝업",
            brand="아디다스",
            venue_name="성수동",
        )
        p2 = Popup(
            title="나이키 팝업",
            brand="나이키",
            venue_name="성수동",
        )
        similarity = service.calculate_popup_similarity(p1, p2)
        # 같은 장소여도 다른 브랜드
        assert similarity < POPUP_DUPLICATE_THRESHOLD


class TestFindDuplicate:
    """중복 찾기 테스트"""

    def test_find_duplicate_event_by_url(self, service, db):
        """URL로 중복 이벤트 찾기"""
        # 기존 이벤트 생성
        existing = Event(
            title="기존 이벤트",
            event_url="https://forms.gle/unique123",
            source_type="manual",
        )
        db.add(existing)
        db.commit()

        # 동일 URL로 중복 검색
        new_data = {
            "title": "새 이벤트",
            "event_url": "https://forms.gle/unique123",
        }
        result = service.find_duplicate_event(db, new_data)

        assert result is not None
        found_event, similarity = result
        assert found_event.id == existing.id
        assert similarity == 1.0

        # 정리
        db.delete(existing)
        db.commit()

    def test_find_duplicate_popup_by_brand_venue(self, service, db):
        """브랜드+장소로 중복 팝업 찾기"""
        # 기존 팝업 생성
        existing = Popup(
            title="기존 팝업",
            brand="테스트브랜드",
            venue_name="테스트장소",
            start_date=date(2024, 12, 1),
            end_date=date(2024, 12, 31),
            source_type="manual",
        )
        db.add(existing)
        db.commit()

        # 동일 브랜드+장소+기간으로 중복 검색
        new_data = {
            "title": "새 팝업",
            "brand": "테스트브랜드",
            "venue_name": "테스트장소",
            "start_date": date(2024, 12, 15),
            "end_date": date(2025, 1, 15),
        }
        result = service.find_duplicate_popup(db, new_data)

        assert result is not None
        found_popup, similarity = result
        assert found_popup.id == existing.id
        assert similarity >= POPUP_DUPLICATE_THRESHOLD

        # 정리
        db.delete(existing)
        db.commit()

    def test_no_duplicate_found(self, service, db):
        """중복 없음"""
        new_data = {
            "title": "완전 새로운 이벤트",
            "event_url": "https://unique-never-seen-before.com/event",
            "organizer": "새로운 주최자",
        }
        result = service.find_duplicate_event(db, new_data)
        assert result is None


class TestMergeData:
    """데이터 병합 테스트"""

    def test_merge_event_fills_empty_fields(self, service):
        """빈 필드 채우기"""
        existing = Event(
            title="기존 제목",
            organizer=None,  # 빈 필드
            event_url="https://example.com",
        )

        new_data = {
            "title": "새 제목",  # 이미 있으므로 무시
            "organizer": "새 주최자",  # 빈 필드 채움
            "summary": "이벤트 요약",  # 빈 필드 채움
        }

        merged = service.merge_event_data(existing, new_data)

        assert "organizer" in merged
        assert merged["organizer"] == "새 주최자"
        assert "summary" in merged
        assert "title" not in merged  # 기존 값 있으므로 병합 안 됨

    def test_merge_popup_fills_empty_fields(self, service):
        """팝업 빈 필드 채우기"""
        existing = Popup(
            title="기존 팝업",
            brand="테스트",
            venue_name=None,
        )

        new_data = {
            "venue_name": "성수동 팝업스토어",
            "address": "서울시 성동구",
        }

        merged = service.merge_popup_data(existing, new_data)

        assert "venue_name" in merged
        assert "address" in merged
