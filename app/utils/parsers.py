import re
import asyncio
from datetime import datetime
from typing import Tuple, Optional, Dict, Any
from urllib.parse import urlparse, parse_qs


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
    from datetime import datetime
    
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
        from .validators import is_naver_content_valid
        
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