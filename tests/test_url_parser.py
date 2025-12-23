"""
Instagram URL 파서 테스트

RIGHT-BICEP 원칙 적용:
- Right: 결과가 올바른가?
- Boundary: 경계값 테스트
- Inverse: 역관계 검증
- Cross-check: 교차 검증
- Error: 에러 조건 테스트
- Performance: 성능 테스트

CORRECT 조건 적용:
- Conformance: 형식 준수
- Ordering: 순서 보장
- Range: 범위 검증
- Reference: 참조 검증
- Existence: 존재 여부
- Cardinality: 개수 검증
- Time: 시간 관련 테스트

테스트 대상:
- parse_instagram_url(): URL 파싱
- InstagramUrlType: URL 타입 분류
"""

import pytest
import sys
from pathlib import Path

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.modules.instagram.services.url_parser import (
    parse_instagram_url,
    InstagramUrlType,
    ParsedInstagramUrl,
    get_url_type_description,
    INSTAGRAM_RESERVED_PATHS,
)


# ============================================================
# Right: 올바른 결과 테스트
# ============================================================


class TestParseInstagramUrlRight:
    """URL 파싱 정상 동작 테스트"""

    def test_parse_single_post_url(self):
        """개별 게시물 URL 파싱"""
        result = parse_instagram_url("https://www.instagram.com/p/ABC123xyz/")
        assert result.url_type == InstagramUrlType.SINGLE_POST
        assert result.post_id == "ABC123xyz"
        assert result.is_supported is True

    def test_parse_single_reel_url(self):
        """개별 릴스 URL 파싱"""
        result = parse_instagram_url("https://www.instagram.com/reel/XYZ789/")
        assert result.url_type == InstagramUrlType.SINGLE_REEL
        assert result.reel_id == "XYZ789"
        assert result.is_supported is True

    def test_parse_account_profile_url(self):
        """계정 프로필 URL 파싱"""
        result = parse_instagram_url("https://www.instagram.com/username/")
        assert result.url_type == InstagramUrlType.ACCOUNT_PROFILE
        assert result.username == "username"
        assert result.is_supported is True

    def test_parse_account_reels_url(self):
        """계정 릴스 URL 파싱"""
        result = parse_instagram_url("https://www.instagram.com/username/reels/")
        assert result.url_type == InstagramUrlType.ACCOUNT_REELS
        assert result.username == "username"
        assert result.is_supported is True

    def test_parse_hashtag_url(self):
        """해시태그 URL 파싱"""
        result = parse_instagram_url("https://www.instagram.com/explore/tags/python/")
        assert result.url_type == InstagramUrlType.HASHTAG
        assert result.hashtag == "python"
        assert result.is_supported is True

    def test_parse_reels_explore_url(self):
        """릴스 탐색 URL 파싱"""
        result = parse_instagram_url("https://www.instagram.com/reels/")
        assert result.url_type == InstagramUrlType.REELS_EXPLORE
        assert result.is_supported is True

    def test_parse_story_url(self):
        """스토리 URL 파싱 (지원 불가)"""
        result = parse_instagram_url("https://www.instagram.com/stories/username/")
        assert result.url_type == InstagramUrlType.STORY
        assert result.username == "username"
        assert result.is_supported is False

    def test_parse_main_feed_url(self):
        """메인 피드 URL 파싱"""
        result = parse_instagram_url("https://www.instagram.com/")
        assert result.url_type == InstagramUrlType.MAIN_FEED
        assert result.is_supported is True


# ============================================================
# Boundary: 경계값 테스트
# ============================================================


class TestParseInstagramUrlBoundary:
    """URL 파싱 경계값 테스트"""

    def test_url_without_trailing_slash(self):
        """트레일링 슬래시 없는 URL"""
        result = parse_instagram_url("https://www.instagram.com/username")
        assert result.url_type == InstagramUrlType.ACCOUNT_PROFILE
        assert result.username == "username"

    def test_url_with_query_params(self):
        """쿼리 파라미터 포함 URL"""
        result = parse_instagram_url(
            "https://www.instagram.com/p/ABC123/?utm_source=test"
        )
        assert result.url_type == InstagramUrlType.SINGLE_POST
        assert result.post_id == "ABC123"

    def test_url_with_hash(self):
        """해시 포함 URL"""
        result = parse_instagram_url("https://www.instagram.com/username/#section")
        assert result.url_type == InstagramUrlType.ACCOUNT_PROFILE
        assert result.username == "username"

    def test_url_without_www(self):
        """www 없는 URL"""
        result = parse_instagram_url("https://instagram.com/p/ABC123/")
        assert result.url_type == InstagramUrlType.SINGLE_POST
        assert result.post_id == "ABC123"

    def test_http_url(self):
        """HTTP URL (HTTPS 아님)"""
        result = parse_instagram_url("http://www.instagram.com/username/")
        assert result.url_type == InstagramUrlType.ACCOUNT_PROFILE
        assert result.username == "username"

    def test_post_id_with_underscore_and_dash(self):
        """언더스코어, 하이픈 포함 게시물 ID"""
        result = parse_instagram_url("https://www.instagram.com/p/ABC_123-xyz/")
        assert result.url_type == InstagramUrlType.SINGLE_POST
        assert result.post_id == "ABC_123-xyz"

    def test_korean_hashtag(self):
        """한글 해시태그"""
        result = parse_instagram_url(
            "https://www.instagram.com/explore/tags/%ED%8C%8C%EC%9D%B4%EC%8D%AC/"
        )
        assert result.url_type == InstagramUrlType.HASHTAG
        # URL 인코딩된 상태로 추출됨

    def test_empty_url(self):
        """빈 URL"""
        result = parse_instagram_url("")
        assert result.url_type == InstagramUrlType.UNKNOWN
        assert result.is_supported is False

    def test_whitespace_url(self):
        """공백만 있는 URL"""
        result = parse_instagram_url("   ")
        assert result.url_type == InstagramUrlType.UNKNOWN

    def test_url_with_leading_trailing_whitespace(self):
        """앞뒤 공백이 있는 URL"""
        result = parse_instagram_url("  https://www.instagram.com/username/  ")
        assert result.url_type == InstagramUrlType.ACCOUNT_PROFILE
        assert result.username == "username"


# ============================================================
# Error: 에러 조건 테스트
# ============================================================


class TestParseInstagramUrlError:
    """URL 파싱 에러 조건 테스트"""

    def test_non_instagram_url(self):
        """Instagram이 아닌 URL"""
        result = parse_instagram_url("https://www.facebook.com/user")
        assert result.url_type == InstagramUrlType.UNKNOWN
        assert result.is_supported is False

    def test_invalid_url_format(self):
        """잘못된 URL 형식"""
        result = parse_instagram_url("not a url")
        assert result.url_type == InstagramUrlType.UNKNOWN

    def test_reserved_path_as_username(self):
        """예약된 경로를 사용자명으로 시도"""
        # 'explore'는 예약된 경로이므로 계정으로 인식되면 안됨
        result = parse_instagram_url("https://www.instagram.com/explore/")
        assert result.url_type == InstagramUrlType.UNKNOWN

    def test_reserved_paths_not_matched_as_profile(self):
        """예약된 경로들이 프로필로 매칭되지 않음"""
        for reserved in ["explore", "reels", "stories", "direct", "accounts", "p", "reel"]:
            result = parse_instagram_url(f"https://www.instagram.com/{reserved}/")
            assert result.url_type != InstagramUrlType.ACCOUNT_PROFILE, f"{reserved} should not be matched as profile"


# ============================================================
# Cross-check: 교차 검증 테스트
# ============================================================


class TestParseInstagramUrlCrossCheck:
    """URL 파싱 교차 검증 테스트"""

    def test_original_url_preserved(self):
        """원본 URL 보존 확인"""
        original = "https://www.instagram.com/p/ABC123/"
        result = parse_instagram_url(original)
        assert result.original_url == original

    def test_url_type_description(self):
        """URL 타입 설명 확인"""
        assert get_url_type_description(InstagramUrlType.SINGLE_POST) == "개별 게시물"
        assert get_url_type_description(InstagramUrlType.ACCOUNT_PROFILE) == "계정 프로필"
        assert get_url_type_description(InstagramUrlType.STORY) == "스토리 (지원 불가)"

    def test_is_supported_consistency(self):
        """is_supported 속성 일관성"""
        supported_types = [
            InstagramUrlType.MAIN_FEED,
            InstagramUrlType.ACCOUNT_PROFILE,
            InstagramUrlType.ACCOUNT_REELS,
            InstagramUrlType.SINGLE_POST,
            InstagramUrlType.SINGLE_REEL,
            InstagramUrlType.REELS_EXPLORE,
            InstagramUrlType.HASHTAG,
        ]
        unsupported_types = [
            InstagramUrlType.STORY,
            InstagramUrlType.UNKNOWN,
        ]

        for url_type in supported_types:
            parsed = ParsedInstagramUrl(url_type=url_type)
            assert parsed.is_supported is True, f"{url_type} should be supported"

        for url_type in unsupported_types:
            parsed = ParsedInstagramUrl(url_type=url_type)
            assert parsed.is_supported is False, f"{url_type} should not be supported"


# ============================================================
# Conformance: 형식 준수 테스트
# ============================================================


class TestParseInstagramUrlConformance:
    """URL 형식 준수 테스트"""

    @pytest.mark.parametrize(
        "url,expected_type,expected_value",
        [
            # 게시물 URL 변형
            ("https://www.instagram.com/p/ABC123/", InstagramUrlType.SINGLE_POST, "ABC123"),
            ("https://instagram.com/p/ABC123", InstagramUrlType.SINGLE_POST, "ABC123"),
            ("http://www.instagram.com/p/ABC123/", InstagramUrlType.SINGLE_POST, "ABC123"),
            # 릴스 URL 변형
            ("https://www.instagram.com/reel/XYZ789/", InstagramUrlType.SINGLE_REEL, "XYZ789"),
            ("https://instagram.com/reel/XYZ789", InstagramUrlType.SINGLE_REEL, "XYZ789"),
            # 계정 URL 변형
            ("https://www.instagram.com/test_user/", InstagramUrlType.ACCOUNT_PROFILE, "test_user"),
            ("https://instagram.com/test_user", InstagramUrlType.ACCOUNT_PROFILE, "test_user"),
        ],
    )
    def test_url_variations(self, url, expected_type, expected_value):
        """다양한 URL 변형 테스트"""
        result = parse_instagram_url(url)
        assert result.url_type == expected_type

        if expected_type == InstagramUrlType.SINGLE_POST:
            assert result.post_id == expected_value
        elif expected_type == InstagramUrlType.SINGLE_REEL:
            assert result.reel_id == expected_value
        elif expected_type == InstagramUrlType.ACCOUNT_PROFILE:
            assert result.username == expected_value


# ============================================================
# Existence: 존재 여부 테스트
# ============================================================


class TestParseInstagramUrlExistence:
    """파싱 결과 필드 존재 여부 테스트"""

    def test_post_url_has_post_id_only(self):
        """게시물 URL은 post_id만 있어야 함"""
        result = parse_instagram_url("https://www.instagram.com/p/ABC123/")
        assert result.post_id == "ABC123"
        assert result.reel_id is None
        assert result.username is None
        assert result.hashtag is None

    def test_account_url_has_username_only(self):
        """계정 URL은 username만 있어야 함"""
        result = parse_instagram_url("https://www.instagram.com/testuser/")
        assert result.username == "testuser"
        assert result.post_id is None
        assert result.reel_id is None
        assert result.hashtag is None

    def test_hashtag_url_has_hashtag_only(self):
        """해시태그 URL은 hashtag만 있어야 함"""
        result = parse_instagram_url("https://www.instagram.com/explore/tags/test/")
        assert result.hashtag == "test"
        assert result.post_id is None
        assert result.reel_id is None
        assert result.username is None


# ============================================================
# 통합 테스트
# ============================================================


class TestParseInstagramUrlIntegration:
    """URL 파서 통합 테스트"""

    def test_all_url_types_covered(self):
        """모든 URL 타입이 테스트되었는지 확인"""
        test_urls = {
            InstagramUrlType.MAIN_FEED: "https://www.instagram.com/",
            InstagramUrlType.ACCOUNT_PROFILE: "https://www.instagram.com/user/",
            InstagramUrlType.ACCOUNT_REELS: "https://www.instagram.com/user/reels/",
            InstagramUrlType.SINGLE_POST: "https://www.instagram.com/p/ABC/",
            InstagramUrlType.SINGLE_REEL: "https://www.instagram.com/reel/XYZ/",
            InstagramUrlType.REELS_EXPLORE: "https://www.instagram.com/reels/",
            InstagramUrlType.HASHTAG: "https://www.instagram.com/explore/tags/test/",
            InstagramUrlType.STORY: "https://www.instagram.com/stories/user/",
        }

        for expected_type, url in test_urls.items():
            result = parse_instagram_url(url)
            assert result.url_type == expected_type, f"Failed for {url}"

    def test_reserved_paths_constant_exists(self):
        """예약된 경로 상수가 존재하는지 확인"""
        assert "explore" in INSTAGRAM_RESERVED_PATHS
        assert "reels" in INSTAGRAM_RESERVED_PATHS
        assert "p" in INSTAGRAM_RESERVED_PATHS
        assert "reel" in INSTAGRAM_RESERVED_PATHS
