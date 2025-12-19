"""
URL 파싱 유틸리티

네이버 전용 파서(ParsedNaverUrl, parse_naver_booking_url, parse_naver_page_info)는
app.modules.naver_booking.utils.parsers로 이동되었습니다.
"""
import re
from datetime import datetime
from typing import Tuple, Optional, Dict, Any
from urllib.parse import urlparse, parse_qs

# Re-export naver-specific parsers for backward compatibility
import warnings as _warnings

def _warn_deprecated():
    _warnings.warn(
        "app.utils.parsers의 네이버 전용 함수들은 deprecated입니다. "
        "app.modules.naver_booking.utils.parsers를 사용하세요.",
        DeprecationWarning,
        stacklevel=3
    )

# Lazy import to avoid circular imports
def __getattr__(name):
    if name in ('ParsedNaverUrl', 'parse_naver_booking_url', 'parse_naver_page_info', 'parse_time_and_stock'):
        _warn_deprecated()
        from app.modules.naver_booking.utils import parsers as naver_parsers
        return getattr(naver_parsers, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Common utility functions (not naver-specific)

def extract_date_only(date_str: Optional[str]) -> Optional[str]:
    """
    날짜 문자열에서 YYYY-MM-DD 형식만 추출합니다.

    Args:
        date_str: 날짜 문자열 (예: 2025-12-15T00:00:00+09:00)

    Returns:
        Optional[str]: YYYY-MM-DD 형식 또는 None
    """
    if not date_str:
        return None

    # T로 시작하는 시간 부분 제거
    if 'T' in date_str:
        date_str = date_str.split('T')[0]

    # YYYY-MM-DD 패턴 확인
    if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        return date_str

    return None


def extract_date_from_url(url: str) -> Optional[str]:
    """
    URL에서 날짜 정보를 추출합니다.

    Args:
        url: URL 문자열

    Returns:
        Optional[str]: 추출된 날짜 문자열 또는 None
    """
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    start_date_time = query_params.get('startDateTime')
    start_date = query_params.get('startDate')

    if start_date_time:
        return start_date_time[0]
    elif start_date:
        return start_date[0]
    else:
        return None


def calculate_interval(start_date_str: Optional[str]) -> Optional[float]:
    """
    URL의 날짜에 따른 모니터링 간격을 계산합니다.

    Args:
        start_date_str: 시작 날짜 문자열

    Returns:
        Optional[float]: 계산된 모니터링 간격(초) 또는 None
    """
    import random

    if start_date_str is None:
        print(f"[Note] Error detected! {start_date_str}")
        return None

    try:
        if start_date_str.find("T") > 0:
            # 공백으로 구분된 시간대 처리
            if " " in start_date_str:
                # 공백을 +로 변환하고 시간 형식 수정
                date_part = start_date_str.replace(" ", "+")
                if "0000" in date_part:
                    date_part = date_part.replace("0000", "00:00")
                start_datetime = datetime.strptime(date_part, "%Y-%m-%dT%H:%M:%S%z")
            else:
                # 0000 형식 처리
                if "0000" in start_date_str:
                    start_date_str = start_date_str.replace("0000", "00:00")
                start_datetime = datetime.strptime(start_date_str, "%Y-%m-%dT%H:%M:%S%z")
        else:
            start_datetime = datetime.strptime(start_date_str + "T00:00:00+0900", "%Y-%m-%dT%H:%M:%S%z")
    except ValueError as e:
        print(f"[Note] Date parsing error! {start_date_str}: {str(e)}")
        return random.uniform(2, 7)

    now = datetime.now(start_datetime.tzinfo)
    delta = start_datetime - now

    if delta.total_seconds() < 0:  # 이미 지난 날짜
        return random.uniform(2, 7)
    if delta.days > 7:  # 7일 이상
        return random.uniform(200, 300)
    if delta.days > 1:  # 1-7일 이내
        return random.uniform(20, 50)
    return random.uniform(3, 10)  # 내일
