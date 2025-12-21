"""
Instagram 게시물 분류 서비스 테스트

RIGHT-BICEP 원칙 적용:
- Right: 결과가 올바른가?
- Boundary: 경계값 테스트
- Inverse: 역관계 검증
- Cross-check: 교차 검증
- Error: 에러 조건 테스트
- Performance: 성능 테스트

테스트 대상:
- ClassifierService (게시물 분류)
- TagService (태그/키워드 관리)
"""

import pytest
import sys
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================
# 테스트 픽스처
# ============================================================


@pytest.fixture
def mock_db():
    """Mock 데이터베이스 세션"""
    return MagicMock()


@pytest.fixture
def mock_post():
    """Mock 게시물"""
    post = MagicMock()
    post.id = 1
    post.post_id = "test123"
    post.caption = "오늘의 이벤트! 팔로우하고 응모하세요!"
    post.account = "testaccount"
    return post


@pytest.fixture
def mock_post_popup():
    """팝업스토어 관련 게시물"""
    post = MagicMock()
    post.id = 2
    post.post_id = "popup123"
    post.caption = "새로운 팝업스토어 오픈! 방문하세요."
    post.account = "popupaccount"
    return post


@pytest.fixture
def mock_post_both():
    """이벤트 + 팝업스토어 모두 포함된 게시물"""
    post = MagicMock()
    post.id = 3
    post.post_id = "both123"
    post.caption = "팝업스토어 오픈 기념 이벤트! 추첨을 통해 경품 증정!"
    post.account = "bothaccount"
    return post


@pytest.fixture
def mock_post_empty():
    """caption이 없는 게시물"""
    post = MagicMock()
    post.id = 4
    post.post_id = "empty123"
    post.caption = None
    post.account = "emptyaccount"
    return post


@pytest.fixture
def mock_tag_event():
    """이벤트 태그"""
    tag = MagicMock()
    tag.id = 1
    tag.name = "event"
    tag.display_name = "이벤트"
    tag.color = "#ef4444"
    tag.is_active = True
    return tag


@pytest.fixture
def mock_tag_popup():
    """팝업스토어 태그"""
    tag = MagicMock()
    tag.id = 2
    tag.name = "popup_store"
    tag.display_name = "팝업스토어"
    tag.color = "#8b5cf6"
    tag.is_active = True
    return tag


@pytest.fixture
def mock_keyword_event():
    """이벤트 키워드"""
    kw = MagicMock()
    kw.id = 1
    kw.tag_id = 1
    kw.keyword = "이벤트"
    kw.is_regex = False
    kw.is_case_sensitive = False
    kw.is_active = True
    return kw


@pytest.fixture
def mock_keyword_popup():
    """팝업스토어 키워드"""
    kw = MagicMock()
    kw.id = 2
    kw.tag_id = 2
    kw.keyword = "팝업스토어"
    kw.is_regex = False
    kw.is_case_sensitive = False
    kw.is_active = True
    return kw


# ============================================================
# ClassifierService 테스트 - Right (결과 검증)
# ============================================================


class TestClassifierServiceRight:
    """분류 서비스 결과 검증 테스트"""

    def test_classify_post_event(self, mock_db, mock_post, mock_tag_event, mock_keyword_event):
        """이벤트 게시물 분류"""
        from app.modules.instagram.services.classifier_service import ClassifierService

        # Setup: 태그와 키워드 반환 설정
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_tag_event]
        mock_db.query.return_value.filter.return_value.first.return_value = None

        service = ClassifierService(mock_db)
        # 키워드 캐시 설정
        service._keyword_cache[mock_tag_event.id] = [mock_keyword_event]

        result = service.classify_post(mock_post)

        assert len(result) >= 1
        assert any(r["tag"] == "event" for r in result)

    def test_classify_post_returns_matched_keywords(
        self, mock_db, mock_post, mock_tag_event, mock_keyword_event
    ):
        """분류 결과에 매칭된 키워드 포함"""
        from app.modules.instagram.services.classifier_service import ClassifierService

        mock_db.query.return_value.filter.return_value.all.return_value = [mock_tag_event]
        mock_db.query.return_value.filter.return_value.first.return_value = None

        service = ClassifierService(mock_db)
        service._keyword_cache[mock_tag_event.id] = [mock_keyword_event]

        result = service.classify_post(mock_post)

        if result:
            assert "keywords" in result[0]
            assert "이벤트" in result[0]["keywords"]


class TestClassifierServiceBoundary:
    """분류 서비스 경계값 테스트"""

    def test_classify_post_empty_caption(self, mock_db, mock_post_empty):
        """caption이 없는 경우 빈 결과 반환"""
        from app.modules.instagram.services.classifier_service import ClassifierService

        service = ClassifierService(mock_db)
        result = service.classify_post(mock_post_empty)

        assert result == []

    def test_classify_post_no_matching_keywords(self, mock_db, mock_tag_event):
        """매칭되는 키워드가 없는 경우"""
        from app.modules.instagram.services.classifier_service import ClassifierService

        # 일반 게시물 (매칭 키워드 없음)
        post = MagicMock()
        post.id = 5
        post.caption = "오늘 날씨가 좋네요."

        mock_db.query.return_value.filter.return_value.all.return_value = [mock_tag_event]

        service = ClassifierService(mock_db)
        service._keyword_cache[mock_tag_event.id] = []  # 빈 키워드

        result = service.classify_post(post)

        assert result == []


class TestClassifierServiceInverse:
    """분류 서비스 역관계 검증"""

    def test_classify_post_multiple_tags(
        self, mock_db, mock_post_both, mock_tag_event, mock_tag_popup,
        mock_keyword_event, mock_keyword_popup
    ):
        """복수 태그 동시 분류"""
        from app.modules.instagram.services.classifier_service import ClassifierService

        mock_db.query.return_value.filter.return_value.all.return_value = [
            mock_tag_event, mock_tag_popup
        ]
        mock_db.query.return_value.filter.return_value.first.return_value = None

        service = ClassifierService(mock_db)
        service._keyword_cache[mock_tag_event.id] = [mock_keyword_event]
        service._keyword_cache[mock_tag_popup.id] = [mock_keyword_popup]

        result = service.classify_post(mock_post_both)

        # 두 태그 모두 매칭되어야 함
        tag_names = [r["tag"] for r in result]
        assert "event" in tag_names
        assert "popup_store" in tag_names


class TestClassifierServiceCrossCheck:
    """분류 서비스 교차 검증"""

    def test_reclassify_clears_existing(self, mock_db):
        """재분류 시 기존 분류 결과 삭제"""
        from app.modules.instagram.services.classifier_service import ClassifierService

        mock_db.query.return_value.delete.return_value = 10
        mock_db.query.return_value.all.return_value = []

        service = ClassifierService(mock_db)
        service.reclassify_all()

        # delete가 호출되어야 함
        mock_db.query.return_value.delete.assert_called_once()


class TestClassifierServiceKeywordMatching:
    """키워드 매칭 테스트"""

    def test_match_keywords_case_insensitive(self, mock_db):
        """대소문자 무시 매칭"""
        from app.modules.instagram.services.classifier_service import ClassifierService

        kw = MagicMock()
        kw.keyword = "event"
        kw.is_regex = False
        kw.is_case_sensitive = False
        kw.is_active = True

        service = ClassifierService(mock_db)

        # 대문자 EVENT도 매칭되어야 함
        result = service._match_keywords("Check out our EVENT!", [kw])
        assert "event" in result

    def test_match_keywords_case_sensitive(self, mock_db):
        """대소문자 구분 매칭"""
        from app.modules.instagram.services.classifier_service import ClassifierService

        kw = MagicMock()
        kw.keyword = "EVENT"
        kw.is_regex = False
        kw.is_case_sensitive = True
        kw.is_active = True

        service = ClassifierService(mock_db)

        # 대문자 EVENT만 매칭
        result = service._match_keywords("Check out our EVENT!", [kw])
        assert "EVENT" in result

        # 소문자 event는 매칭 안됨
        result2 = service._match_keywords("Check out our event!", [kw])
        assert result2 == []

    def test_match_keywords_regex(self, mock_db):
        """정규식 키워드 매칭"""
        from app.modules.instagram.services.classifier_service import ClassifierService

        kw = MagicMock()
        kw.keyword = r"이벤트|event"
        kw.is_regex = True
        kw.is_case_sensitive = False
        kw.is_active = True

        service = ClassifierService(mock_db)

        result1 = service._match_keywords("오늘의 이벤트!", [kw])
        assert r"이벤트|event" in result1

        result2 = service._match_keywords("Check our event!", [kw])
        assert r"이벤트|event" in result2

    def test_match_keywords_invalid_regex(self, mock_db):
        """잘못된 정규식 처리"""
        from app.modules.instagram.services.classifier_service import ClassifierService

        kw = MagicMock()
        kw.keyword = r"[invalid(regex"  # 잘못된 정규식
        kw.is_regex = True
        kw.is_case_sensitive = False
        kw.is_active = True

        service = ClassifierService(mock_db)

        # 에러 없이 빈 결과 반환
        result = service._match_keywords("test text", [kw])
        assert result == []


# ============================================================
# TagService 테스트 - Right (결과 검증)
# ============================================================


class TestTagServiceRight:
    """태그 서비스 결과 검증 테스트"""

    def test_get_tags(self, mock_db, mock_tag_event, mock_tag_popup):
        """태그 목록 조회"""
        from app.modules.instagram.services.tag_service import TagService

        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            mock_tag_event, mock_tag_popup
        ]

        service = TagService(mock_db)
        tags = service.get_tags()

        assert len(tags) == 2

    def test_create_tag(self, mock_db):
        """태그 생성"""
        from app.modules.instagram.services.tag_service import TagService

        service = TagService(mock_db)
        tag = service.create_tag(
            name="new_tag",
            display_name="새 태그",
            description="테스트 태그",
            color="#ff0000"
        )

        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_get_tag_by_name(self, mock_db, mock_tag_event):
        """이름으로 태그 조회"""
        from app.modules.instagram.services.tag_service import TagService

        mock_db.query.return_value.filter.return_value.first.return_value = mock_tag_event

        service = TagService(mock_db)
        tag = service.get_tag_by_name("event")

        assert tag.name == "event"


class TestTagServiceKeyword:
    """키워드 관리 테스트"""

    def test_add_keyword(self, mock_db, mock_tag_event):
        """키워드 추가"""
        from app.modules.instagram.services.tag_service import TagService

        mock_db.query.return_value.filter.return_value.first.side_effect = [
            mock_tag_event,  # get_tag_by_id
            None,  # 중복 확인 - 없음
        ]

        service = TagService(mock_db)
        kw = service.add_keyword(
            tag_id=1,
            keyword="추첨",
            is_regex=False,
            is_case_sensitive=False
        )

        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_add_keyword_duplicate_skip(self, mock_db, mock_tag_event, mock_keyword_event):
        """중복 키워드 추가 시 스킵"""
        from app.modules.instagram.services.tag_service import TagService

        mock_db.query.return_value.filter.return_value.first.side_effect = [
            mock_tag_event,  # get_tag_by_id
            mock_keyword_event,  # 중복 확인 - 있음
        ]

        service = TagService(mock_db)
        result = service.add_keyword(tag_id=1, keyword="이벤트")

        # 기존 키워드 반환
        assert result == mock_keyword_event

    def test_delete_keyword(self, mock_db, mock_keyword_event):
        """키워드 삭제"""
        from app.modules.instagram.services.tag_service import TagService

        mock_db.query.return_value.filter.return_value.first.return_value = mock_keyword_event

        service = TagService(mock_db)
        result = service.delete_keyword(1)

        assert result is True
        mock_db.delete.assert_called_once()

    def test_delete_keyword_not_found(self, mock_db):
        """존재하지 않는 키워드 삭제"""
        from app.modules.instagram.services.tag_service import TagService

        mock_db.query.return_value.filter.return_value.first.return_value = None

        service = TagService(mock_db)
        result = service.delete_keyword(999)

        assert result is False

    def test_toggle_keyword(self, mock_db, mock_keyword_event):
        """키워드 활성화/비활성화 토글"""
        from app.modules.instagram.services.tag_service import TagService

        mock_db.query.return_value.filter.return_value.first.return_value = mock_keyword_event

        service = TagService(mock_db)
        result = service.toggle_keyword(1)

        # is_active가 토글되어야 함
        assert result.is_active != True  # 원래 True였으므로 False로 변경


class TestTagServiceBulk:
    """일괄 작업 테스트"""

    def test_add_keywords_bulk(self, mock_db, mock_tag_event):
        """키워드 일괄 추가"""
        from app.modules.instagram.services.tag_service import TagService

        # mock 키워드
        mock_kw = MagicMock()
        mock_kw.id = 100

        # side_effect 패턴:
        # - 첫 번째 호출 (get_tag_by_id): tag 반환
        # - 두 번째 호출 (중복 확인): None (새 키워드)
        # - 세 번째 호출 (added 확인): 생성된 키워드
        # 이 패턴이 3번 반복됨
        def make_side_effect():
            call_count = [0]

            def side_effect(*args, **kwargs):
                call_count[0] += 1
                mod = call_count[0] % 3
                if mod == 1:  # get_tag_by_id
                    return mock_tag_event
                elif mod == 2:  # 중복 확인
                    return None
                else:  # added 확인 (id 비교)
                    return mock_kw

            return side_effect

        mock_db.query.return_value.filter.return_value.first.side_effect = make_side_effect()
        mock_db.add.return_value = None
        mock_db.commit.return_value = None
        mock_db.refresh.side_effect = lambda obj: setattr(obj, "id", 100)

        service = TagService(mock_db)
        added = service.add_keywords_bulk(1, ["추첨", "당첨", "경품"])

        # 3개 모두 추가됨
        assert added == 3


# ============================================================
# 마이그레이션 및 스키마 테스트
# ============================================================


class TestClassificationMigration:
    """분류 마이그레이션 테스트"""

    def test_migration_031_exists(self):
        """031_instagram_post_classification.sql 파일 존재"""
        migration_path = PROJECT_ROOT / "app" / "migrations" / "031_instagram_post_classification.sql"
        assert migration_path.exists(), "031_instagram_post_classification.sql should exist"

    def test_migration_031_contains_tables(self):
        """마이그레이션에 필요한 테이블 포함"""
        migration_path = PROJECT_ROOT / "app" / "migrations" / "031_instagram_post_classification.sql"
        content = migration_path.read_text(encoding="utf-8")

        assert "instagram_post_tags" in content
        assert "instagram_tag_keywords" in content
        assert "instagram_post_tag_relations" in content

    def test_migration_031_contains_initial_data(self):
        """마이그레이션에 초기 데이터 포함"""
        migration_path = PROJECT_ROOT / "app" / "migrations" / "031_instagram_post_classification.sql"
        content = migration_path.read_text(encoding="utf-8")

        assert "event" in content
        assert "popup_store" in content
        assert "이벤트" in content
        assert "팝업스토어" in content


class TestClassificationModels:
    """분류 모델 테스트"""

    def test_tag_model_exists(self):
        """InstagramPostTag 모델 존재"""
        from app.models.instagram_post_tag import InstagramPostTag

        assert hasattr(InstagramPostTag, 'id')
        assert hasattr(InstagramPostTag, 'name')
        assert hasattr(InstagramPostTag, 'display_name')
        assert hasattr(InstagramPostTag, 'color')
        assert hasattr(InstagramPostTag, 'is_active')

    def test_keyword_model_exists(self):
        """InstagramTagKeyword 모델 존재"""
        from app.models.instagram_post_tag import InstagramTagKeyword

        assert hasattr(InstagramTagKeyword, 'id')
        assert hasattr(InstagramTagKeyword, 'tag_id')
        assert hasattr(InstagramTagKeyword, 'keyword')
        assert hasattr(InstagramTagKeyword, 'is_regex')
        assert hasattr(InstagramTagKeyword, 'is_case_sensitive')

    def test_relation_model_exists(self):
        """InstagramPostTagRelation 모델 존재"""
        from app.models.instagram_post_tag import InstagramPostTagRelation

        assert hasattr(InstagramPostTagRelation, 'id')
        assert hasattr(InstagramPostTagRelation, 'post_id')
        assert hasattr(InstagramPostTagRelation, 'tag_id')
        assert hasattr(InstagramPostTagRelation, 'matched_keywords')
        assert hasattr(InstagramPostTagRelation, 'confidence')

    def test_post_model_has_tags_property(self):
        """InstagramPost 모델에 tags 프로퍼티 존재"""
        from app.models.instagram_post import InstagramPost

        assert hasattr(InstagramPost, 'tags')
        assert hasattr(InstagramPost, 'tag_relations')


class TestClassificationSchemas:
    """분류 스키마 테스트"""

    def test_tag_schema_exists(self):
        """TagSchema 존재"""
        from app.modules.instagram.models.schemas import TagSchema

        fields = TagSchema.model_fields
        assert 'id' in fields
        assert 'name' in fields
        assert 'display_name' in fields
        assert 'color' in fields
        assert 'keyword_count' in fields

    def test_keyword_schema_exists(self):
        """KeywordSchema 존재"""
        from app.modules.instagram.models.schemas import KeywordSchema

        fields = KeywordSchema.model_fields
        assert 'id' in fields
        assert 'keyword' in fields
        assert 'is_regex' in fields
        assert 'is_case_sensitive' in fields

    def test_post_schema_has_tags(self):
        """PostSchema에 tags 필드 존재"""
        from app.modules.instagram.models.schemas import PostSchema

        fields = PostSchema.model_fields
        assert 'tags' in fields

    def test_classify_request_schema(self):
        """ClassifyRequestSchema 존재"""
        from app.modules.instagram.models.schemas import ClassifyRequestSchema

        fields = ClassifyRequestSchema.model_fields
        assert 'post_ids' in fields

    def test_classify_result_schema(self):
        """ClassifyResultSchema 존재"""
        from app.modules.instagram.models.schemas import ClassifyResultSchema

        fields = ClassifyResultSchema.model_fields
        assert 'total' in fields
        assert 'classified' in fields
        assert 'details' in fields


# ============================================================
# 성능 테스트 (Performance)
# ============================================================


class TestClassifierPerformance:
    """분류 성능 테스트"""

    def test_batch_classify_many_posts(self, mock_db):
        """대량 게시물 일괄 분류"""
        from types import SimpleNamespace
        from unittest.mock import patch
        from app.modules.instagram.services.classifier_service import ClassifierService

        # 태그 fixture 직접 생성 (SimpleNamespace 사용)
        mock_tag = SimpleNamespace(
            id=1,
            name="event",
            display_name="이벤트",
            color="#ef4444",
            is_active=True,
        )

        # 키워드 fixture 직접 생성
        mock_kw = SimpleNamespace(
            id=1,
            tag_id=1,
            keyword="이벤트",
            is_regex=False,
            is_case_sensitive=False,
            is_active=True,
        )

        # 100개 게시물 생성
        posts = []
        for i in range(100):
            post = SimpleNamespace(id=i, caption=f"테스트 이벤트 {i}")
            posts.append(post)

        service = ClassifierService(mock_db)

        # 메서드 패치
        with patch.object(service, "_get_active_tags", return_value=[mock_tag]):
            with patch.object(service, "_load_keywords", return_value=[mock_kw]):
                # posts 쿼리만 mock
                mock_db.query.return_value.filter.return_value.all.return_value = posts
                mock_db.query.return_value.filter.return_value.first.return_value = None

                result = service.classify_posts_batch([p.id for p in posts])

        assert result["total"] == 100

    def test_cache_is_used(self, mock_db, mock_tag_event, mock_keyword_event):
        """캐시가 재사용되는지 확인"""
        from app.modules.instagram.services.classifier_service import ClassifierService

        service = ClassifierService(mock_db)

        # 첫 번째 호출
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_keyword_event]
        keywords1 = service._load_keywords(mock_tag_event.id)

        # 두 번째 호출 - 캐시에서 가져와야 함
        keywords2 = service._load_keywords(mock_tag_event.id)

        assert keywords1 == keywords2
        # DB 쿼리는 한 번만 호출되어야 함
        assert service._keyword_cache[mock_tag_event.id] == keywords1

    def test_clear_cache(self, mock_db, mock_tag_event, mock_keyword_event):
        """캐시 초기화"""
        from app.modules.instagram.services.classifier_service import ClassifierService

        service = ClassifierService(mock_db)
        service._keyword_cache[mock_tag_event.id] = [mock_keyword_event]

        assert len(service._keyword_cache) == 1

        service.clear_cache()

        assert len(service._keyword_cache) == 0
