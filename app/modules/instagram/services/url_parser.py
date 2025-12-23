"""
Instagram URL 파서

다양한 Instagram URL을 파싱하여 타입과 파라미터를 추출합니다.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional
import re


class InstagramUrlType(Enum):
    """Instagram URL 타입"""

    MAIN_FEED = "main_feed"
    ACCOUNT_PROFILE = "account_profile"
    ACCOUNT_REELS = "account_reels"
    SINGLE_POST = "single_post"
    SINGLE_REEL = "single_reel"
    REELS_EXPLORE = "reels_explore"
    HASHTAG = "hashtag"
    STORY = "story"  # 지원 불가
    UNKNOWN = "unknown"


@dataclass
class ParsedInstagramUrl:
    """파싱된 Instagram URL 정보"""

    url_type: InstagramUrlType
    username: Optional[str] = None
    post_id: Optional[str] = None
    reel_id: Optional[str] = None
    hashtag: Optional[str] = None
    original_url: str = ""

    @property
    def is_supported(self) -> bool:
        """지원되는 URL 타입인지 확인"""
        return self.url_type not in (
            InstagramUrlType.STORY,
            InstagramUrlType.UNKNOWN,
        )


# Instagram 시스템 경로 (사용자명이 아닌 것들)
INSTAGRAM_RESERVED_PATHS = {
    "explore",
    "reels",
    "stories",
    "direct",
    "accounts",
    "p",
    "reel",
    "tv",
    "about",
    "legal",
    "api",
    "developer",
    "graphql",
}


def parse_instagram_url(url: str) -> ParsedInstagramUrl:
    """
    Instagram URL을 파싱하여 타입과 파라미터 추출

    Args:
        url: Instagram URL

    Returns:
        ParsedInstagramUrl: 파싱된 URL 정보
    """
    # URL 정규화
    url = url.strip()
    if not url:
        return ParsedInstagramUrl(url_type=InstagramUrlType.UNKNOWN, original_url=url)

    # 패턴 정의 (순서 중요: 더 구체적인 패턴이 먼저)
    patterns = [
        # 개별 게시물: /p/{id}/
        (
            InstagramUrlType.SINGLE_POST,
            r"instagram\.com/p/([A-Za-z0-9_-]+)",
            lambda m: {"post_id": m.group(1)},
        ),
        # 개별 릴스: /reel/{id}/
        (
            InstagramUrlType.SINGLE_REEL,
            r"instagram\.com/reel/([A-Za-z0-9_-]+)",
            lambda m: {"reel_id": m.group(1)},
        ),
        # 해시태그: /explore/tags/{hashtag}/
        (
            InstagramUrlType.HASHTAG,
            r"instagram\.com/explore/tags/([^/?#]+)",
            lambda m: {"hashtag": m.group(1)},
        ),
        # 스토리: /stories/{username}/
        (
            InstagramUrlType.STORY,
            r"instagram\.com/stories/([^/?#]+)",
            lambda m: {"username": m.group(1)},
        ),
        # 계정 릴스: /{username}/reels/
        (
            InstagramUrlType.ACCOUNT_REELS,
            r"instagram\.com/([^/?#]+)/reels/?(?:\?|#|$)",
            lambda m: {"username": m.group(1)}
            if m.group(1) not in INSTAGRAM_RESERVED_PATHS
            else None,
        ),
        # 릴스 탐색: /reels/
        (
            InstagramUrlType.REELS_EXPLORE,
            r"instagram\.com/reels/?(?:\?|#|$)",
            lambda m: {},
        ),
        # 계정 프로필: /{username}/
        (
            InstagramUrlType.ACCOUNT_PROFILE,
            r"instagram\.com/([^/?#]+)/?(?:\?|#|$)",
            lambda m: {"username": m.group(1)}
            if m.group(1) not in INSTAGRAM_RESERVED_PATHS
            else None,
        ),
    ]

    for url_type, pattern, extractor in patterns:
        match = re.search(pattern, url)
        if match:
            extracted = extractor(match)
            if extracted is not None:
                return ParsedInstagramUrl(
                    url_type=url_type,
                    original_url=url,
                    **extracted,
                )

    # 메인 피드 체크: instagram.com 또는 instagram.com/
    if re.search(r"instagram\.com/?(?:\?|#|$)", url):
        return ParsedInstagramUrl(url_type=InstagramUrlType.MAIN_FEED, original_url=url)

    return ParsedInstagramUrl(url_type=InstagramUrlType.UNKNOWN, original_url=url)


def get_url_type_description(url_type: InstagramUrlType) -> str:
    """URL 타입에 대한 설명 반환"""
    descriptions = {
        InstagramUrlType.MAIN_FEED: "메인 피드",
        InstagramUrlType.ACCOUNT_PROFILE: "계정 프로필",
        InstagramUrlType.ACCOUNT_REELS: "계정 릴스",
        InstagramUrlType.SINGLE_POST: "개별 게시물",
        InstagramUrlType.SINGLE_REEL: "개별 릴스",
        InstagramUrlType.REELS_EXPLORE: "릴스 탐색",
        InstagramUrlType.HASHTAG: "해시태그",
        InstagramUrlType.STORY: "스토리 (지원 불가)",
        InstagramUrlType.UNKNOWN: "알 수 없음",
    }
    return descriptions.get(url_type, "알 수 없음")
