"""
Facebook URL 파서

다양한 Facebook URL을 파싱하여 타입과 파라미터를 추출합니다.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional
import re
from urllib.parse import urlparse, parse_qs


class FacebookUrlType(Enum):
    """Facebook URL 타입."""

    MAIN_FEED = "main_feed"          # https://www.facebook.com/
    USER_PROFILE = "user_profile"    # https://www.facebook.com/{username}
    PAGE = "page"                    # https://www.facebook.com/{page_name}
    GROUP = "group"                  # https://www.facebook.com/groups/{group_id}
    SINGLE_POST = "single_post"      # https://www.facebook.com/{user}/posts/{post_id}
    WATCH = "watch"                  # https://www.facebook.com/watch/
    MARKETPLACE = "marketplace"      # https://www.facebook.com/marketplace/
    REEL = "reel"                    # https://www.facebook.com/reel/{reel_id}
    UNKNOWN = "unknown"


@dataclass
class ParsedFacebookUrl:
    """파싱된 Facebook URL 정보."""

    url_type: FacebookUrlType
    username: Optional[str] = None
    page_name: Optional[str] = None
    group_id: Optional[str] = None
    post_id: Optional[str] = None
    reel_id: Optional[str] = None
    original_url: str = ""

    @property
    def is_supported(self) -> bool:
        """지원되는 URL 타입인지 확인."""
        return self.url_type not in (FacebookUrlType.UNKNOWN,)


# Facebook 예약 경로 (사용자명/페이지명이 아닌 것들)
FACEBOOK_RESERVED_PATHS = {
    "groups",
    "watch",
    "marketplace",
    "reel",
    "reels",
    "pages",
    "events",
    "live",
    "gaming",
    "ads",
    "business",
    "help",
    "about",
    "legal",
    "privacy",
    "settings",
    "notifications",
    "messages",
    "friends",
    "profile.php",
    "permalink.php",
    "photo.php",
    "video.php",
    "story.php",
}


def parse_facebook_url(url: str) -> ParsedFacebookUrl:
    """
    Facebook URL을 파싱하여 타입과 파라미터를 반환합니다.

    Args:
        url: Facebook URL 문자열

    Returns:
        ParsedFacebookUrl 인스턴스
    """
    if not url:
        return ParsedFacebookUrl(url_type=FacebookUrlType.UNKNOWN, original_url=url)

    try:
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        path_parts = [p for p in path.split("/") if p]
        params = parse_qs(parsed.query)
    except Exception:
        return ParsedFacebookUrl(url_type=FacebookUrlType.UNKNOWN, original_url=url)

    # 메인 피드
    if not path or path in ("", "/"):
        return ParsedFacebookUrl(
            url_type=FacebookUrlType.MAIN_FEED,
            original_url=url,
        )

    first = path_parts[0].lower() if path_parts else ""

    # 그룹
    if first == "groups":
        group_id = path_parts[1] if len(path_parts) > 1 else None
        return ParsedFacebookUrl(
            url_type=FacebookUrlType.GROUP,
            group_id=group_id,
            original_url=url,
        )

    # Watch
    if first == "watch":
        return ParsedFacebookUrl(
            url_type=FacebookUrlType.WATCH,
            original_url=url,
        )

    # Marketplace
    if first == "marketplace":
        return ParsedFacebookUrl(
            url_type=FacebookUrlType.MARKETPLACE,
            original_url=url,
        )

    # Reel
    if first == "reel":
        reel_id = path_parts[1] if len(path_parts) > 1 else None
        return ParsedFacebookUrl(
            url_type=FacebookUrlType.REEL,
            reel_id=reel_id,
            original_url=url,
        )

    # 단일 게시물 /{user}/posts/{post_id}
    if len(path_parts) >= 3 and path_parts[1].lower() == "posts":
        return ParsedFacebookUrl(
            url_type=FacebookUrlType.SINGLE_POST,
            username=path_parts[0],
            post_id=path_parts[2],
            original_url=url,
        )

    # 사용자 프로필 또는 페이지 /{username_or_page}
    if len(path_parts) == 1 and first not in FACEBOOK_RESERVED_PATHS:
        return ParsedFacebookUrl(
            url_type=FacebookUrlType.USER_PROFILE,
            username=path_parts[0],
            original_url=url,
        )

    return ParsedFacebookUrl(url_type=FacebookUrlType.UNKNOWN, original_url=url)


def extract_post_id_from_url(url: str) -> Optional[str]:
    """URL에서 Facebook 게시물 ID를 추출합니다."""
    parsed = parse_facebook_url(url)
    return parsed.post_id


def is_facebook_url(url: str) -> bool:
    """주어진 URL이 Facebook URL인지 확인합니다."""
    try:
        parsed = urlparse(url)
        return parsed.netloc in ("www.facebook.com", "facebook.com", "m.facebook.com")
    except Exception:
        return False
