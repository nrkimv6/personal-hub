from bs4 import BeautifulSoup
import re


def is_full_reservation(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    error_title = soup.find('h1', class_='error_title')

    if error_title and "운영하지 않는" in error_title.text:
        return True
    return False


def is_page_availabe(html_content):
    # Remove all spaces and newlines for comparison
    normalized_content = re.sub(r'\s+', '', html_content)

    # Check if specific unwanted HTML tag with content exists
    soup = BeautifulSoup(html_content, 'html.parser')
    error_tag = soup.find('h1', class_='error_title')
    if error_tag and "운영하지 않는" in error_tag.get_text(strip=True):
        print("Page contains the error message. Skipping...")
        return False

    # Check if content matches an unwanted static page
    unwanted_content = '''
    <html lang="ko"><head>
    <meta charset="utf-8"><meta httpequiv="x-ua-compatible" content="ie=edge">
    <meta name="description" content="네이버 예약이 연동된 곳 어디서나 바로 예약하고, 네이버 예약 홈(나의예약)에서 모두 관리할 수 있습니다.">
    <title data-react-helmet="true">네이버 예약</title>
    </head><body></body></html>
    '''
    # Normalize unwanted static content
    normalized_unwanted_content = re.sub(r'\s+', '', unwanted_content)

    # Compare normalized contents
    if normalized_content == normalized_unwanted_content:
        print("Content matches the unwanted static page. Skipping...")
        return False

    return True


def is_content_valid(html_content, level):
    if level > 0:
        if not is_page_availabe(html_content):
            return None

    if level > 1:
        soup = BeautifulSoup(html_content, 'html.parser')
        # # disabled 속성이 없는 버튼 필터링
        #     enabled_buttons = [button for button in buttons if not button.has_attr('disabled')]
        #
        #     if len(enabled_buttons) > 0:
        #         return True
        #     else:
        #         return False

        # 첫 번째 조건: btn_time 클래스가 있고 unselectable 클래스가 없는 버튼 찾기
        buttons = soup.select('div.section_content > div.time_area > div > ul > li > button')
        filtered_buttons = [button for button in buttons if
                            'btn_time' in button['class'] and 'unselectable' not in button['class']]

        # 결과 출력 (첫 번째 조건)
        print("Filtered buttons (Condition 1):")
        for button in filtered_buttons:
            print(button.text)

        if len(filtered_buttons) > 0:
            return [button.text for button in filtered_buttons]

        # 두 번째 조건: sold_out 클래스가 없는 li.item 요소 찾기
        items = soup.select('div.schedule_time > div > div > div > ul.list_time > li.item')
        filtered_items = [item for item in items if 'sold_out' not in item['class']]

        # 결과 출력 (두 번째 조건)
        print("Filtered items (Condition 2):")
        for item in filtered_items:
            print(item.text)

        if len(filtered_items) > 0:
            return [item.text for item in filtered_items]

        return None
    else:
        return ""

    # Example usage within your script when processing new_content:
    # if is_content_valid(new_content):
    #     print("Content is valid and does not match the error or unwanted static page.")
    # else:
    #     print("Detected unwanted content. No actions will be performed.")
