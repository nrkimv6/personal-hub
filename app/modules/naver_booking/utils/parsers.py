"""
네이버 예약 URL 파싱 유틸리티
"""
import re
from typing import Tuple, Optional, Dict, Any
from urllib.parse import urlparse, parse_qs
from dataclasses import dataclass


@dataclass
class ParsedNaverUrl:
    """네이버 예약 URL 파싱 결과"""
    category: str
    business_id: str
    item_id: str
    start_date: Optional[str] = None
    business_type_id: Optional[str] = None
    is_valid: bool = True
    error: Optional[str] = None


def parse_naver_booking_url(url: str) -> ParsedNaverUrl:
    """
    네이버 예약 URL에서 정보를 추출합니다.

    URL 형식: /booking/{category}/bizes/{businessId}/items/{itemId}?startDateTime=...
    또는: https://booking.naver.com/booking/{category}/bizes/{businessId}/items/{itemId}?startDateTime=...

    Args:
        url: 네이버 예약 URL

    Returns:
        ParsedNaverUrl: 파싱된 URL 정보
    """
    try:
        parsed = urlparse(url)
        path = parsed.path

        # /booking/{category}/bizes/{businessId}/items/{itemId} 패턴 매칭
        pattern = r'/booking/([^/]+)/bizes/(\d+)/items/(\d+)'
        match = re.search(pattern, path)

        if not match:
            return ParsedNaverUrl(
                category="", business_id="", item_id="",
                is_valid=False, error="Invalid URL format"
            )

        category = match.group(1)
        business_id = match.group(2)
        item_id = match.group(3)

        # 쿼리 파라미터에서 날짜 추출
        query_params = parse_qs(parsed.query)
        start_date = None
        if 'startDateTime' in query_params:
            start_date = query_params['startDateTime'][0]
        elif 'startDate' in query_params:
            start_date = query_params['startDate'][0]

        # businessTypeId 추출 (있는 경우)
        business_type_id = None
        if 'businessTypeId' in query_params:
            business_type_id = query_params['businessTypeId'][0]

        return ParsedNaverUrl(
            category=category,
            business_id=business_id,
            item_id=item_id,
            start_date=start_date,
            business_type_id=business_type_id,
            is_valid=True
        )
    except Exception as e:
        return ParsedNaverUrl(
            category="", business_id="", item_id="",
            is_valid=False, error=str(e)
        )


def parse_time_and_stock(button_text: str) -> Tuple[str, str]:
    """
    버튼 텍스트에서 시간과 매수 정보를 추출합니다.

    Args:
        button_text: 버튼 텍스트

    Returns:
        Tuple[str, str]: (시간 문자열, 매수 문자열)
    """
    # 시간 패턴 (오전/오후 HH:MM)
    time_pattern = r'(오전|오후)\s+\d{1,2}:\d{2}'
    time_match = re.search(time_pattern, button_text)
    time_str = time_match.group(0) if time_match else ""

    # 매수 패턴 (숫자+매)
    stock_pattern = r'(\d+)매'
    stock_match = re.search(stock_pattern, button_text)
    stock_str = stock_match.group(1) if stock_match else "0"

    return time_str, stock_str


def parse_naver_page_info(html_content: str) -> Dict[str, Any]:
    """
    HTML 콘텐츠에서 페이지 정보를 추출합니다.

    Args:
        html_content: HTML 콘텐츠

    Returns:
        Dict[str, Any]: 추출된 페이지 정보
    """
    from bs4 import BeautifulSoup
    from .validators import is_naver_content_valid

    result = {
        "title": "",
        "times": [],
        "stocks": [],
        "available": False
    }

    try:
        soup = BeautifulSoup(html_content, 'html.parser')

        # 제목 추출
        title_elem = soup.select_one('h2.detail_title, h2.title, div.title')
        if title_elem:
            result["title"] = title_elem.get_text(strip=True)

        # 시간 및 매수 정보 추출
        valid_items = is_naver_content_valid(html_content, level=2)
        if valid_items and isinstance(valid_items, list):
            result["available"] = True

            for item in valid_items:
                time_str, stock_str = parse_time_and_stock(item)
                if time_str:
                    result["times"].append(time_str)
                    if stock_str:
                        result["stocks"].append(f"{time_str}: {stock_str}매")

    except Exception as e:
        print(f"페이지 정보 파싱 중 오류 발생: {str(e)}")

    return result
