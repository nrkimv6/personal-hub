from bs4 import BeautifulSoup
import re
import time
from typing import Optional, List, Union


def is_full_reservation(html_content: str) -> bool:
    """
    페이지가 예약 마감되었는지 확인합니다.
    
    Args:
        html_content: HTML 콘텐츠
        
    Returns:
        bool: 예약 마감 여부
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    error_title = soup.find('h1', class_='error_title')

    if error_title and "운영하지 않는" in error_title.text:
        return True
    return False


def is_page_available(html_content: str) -> bool:
    """
    페이지가 유효한지 확인합니다.
    
    Args:
        html_content: HTML 콘텐츠
        
    Returns:
        bool: 페이지 유효성 여부
    """
    # 공백과 줄바꿈 제거
    normalized_content = re.sub(r'\s+', '', html_content)

    # 특정 오류 메시지 확인
    soup = BeautifulSoup(html_content, 'html.parser')
    error_tag = soup.find('h1', class_='error_title')
    if error_tag and "운영하지 않는" in error_tag.get_text(strip=True):
        print("Page contains the error message. Skipping...")
        return False

    # 원치 않는 정적 페이지 확인
    unwanted_content = '''
    <html lang="ko"><head>
    <meta charset="utf-8"><meta httpequiv="x-ua-compatible" content="ie=edge">
    <meta name="description" content="네이버 예약이 연동된 곳 어디서나 바로 예약하고, 네이버 예약 홈(나의예약)에서 모두 관리할 수 있습니다.">
    <title data-react-helmet="true">네이버 예약</title>
    </head><body></body></html>
    '''
    # 원치 않는 정적 콘텐츠 정규화
    normalized_unwanted_content = re.sub(r'\s+', '', unwanted_content)

    # 정규화된 콘텐츠 비교
    if normalized_content == normalized_unwanted_content:
        print("Content matches the unwanted static page. Skipping...")
        return False

    return True


def is_content_valid(html_content: str, level: int = 2, desired_day: Optional[int] = None) -> Union[None, str, List[str]]:
    """
    HTML 콘텐츠의 유효성을 검사하고 예약 가능한 시간 목록을 반환합니다.
    
    Args:
        html_content: HTML 콘텐츠
        level: 검증 레벨 (0: 검증 없음, 1: 기본 검증, 2: 상세 검증)
        desired_day: 원하는 날짜 (선택 사항)
        
    Returns:
        None: 유효하지 않은 경우
        빈 문자열: 기본 검증만 통과한 경우
        시간 목록: 예약 가능한 시간 목록
    """
    if level > 0:
        if not is_page_available(html_content):
            return None

    if level > 1:
        soup = BeautifulSoup(html_content, 'html.parser')

        # 첫 번째 조건: btn_time 클래스가 있고 unselectable 클래스가 없는 버튼 찾기
        buttons = soup.select('div.section_content > div.time_area > div > ul > li > button')
        filtered_buttons = [button for button in buttons if
                            'btn_time' in button.get('class', []) and 'unselectable' not in button.get('class', [])]

        # 결과 출력 (첫 번째 조건)
        print("Filtered buttons (Condition 1):")
        for button in filtered_buttons:
            print(button.text)

        if len(filtered_buttons) > 0:
            return [button.text for button in filtered_buttons]

        # 새로운 조건 추가: #calendar > table > tbody > tr:nth-child(n) > td.on > a.calendar-date 확인
        on_date = soup.select_one('#calendar > table > tbody > tr > td.on > a.calendar-date')

        if not on_date:
            print("No .on date found. Checking for desired day...")
            if desired_day:
                all_dates = soup.select('#calendar > table > tbody > tr > td > a.calendar-date > span.num')
                for date in all_dates:
                    if date.text.strip() == str(desired_day):
                        print(f"Found desired day: {desired_day}")
                        # 크롤링 환경에서는 클릭이 불가능하므로 주석 처리
                        # date.find_parent('a').click()  # 원하는 날짜 클릭
                        # time.sleep(10)  # 10초 대기
                        break
                else:
                    print(f"Desired day {desired_day} not found")
                    return None
            else:
                print("No desired day specified")
                return None

        # 두 번째 조건: sold_out 클래스가 없는 li.item 요소 찾기
        items = soup.select('div.schedule_time > div > div > div > ul.list_time > li.item')
        filtered_items = [item for item in items if 'sold_out' not in item.get('class', [])]

        # 결과 출력 (두 번째 조건)
        print("Filtered items (Condition 2):")
        for item in filtered_items:
            print(item.text)

        if len(filtered_items) > 0:
            return [item.text for item in filtered_items]

        return None
    else:
        return "" 