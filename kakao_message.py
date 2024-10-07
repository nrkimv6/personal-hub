import json

import requests

from initialize_kakao import generate_access_token


def send_message(message,link_url):
    access_token = generate_access_token()
    # This function assumes you have configured the Kakao API token and other details
    # You need to set up Kakao API token and endpoint details here
    url = 'https://kapi.kakao.com/v2/api/talk/memo/default/send'
    headers = {
        'Authorization': f"Bearer {access_token}",
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    data = {
        'template_object': json.dumps({
            'object_type': 'text',
            'text': message,
            'link': {
                'web_url': link_url,
                'mobile_web_url': link_url
            },
            'button_title': '가보기'
        })
    }
    response = requests.post(url, headers=headers, data=data)
    if response.status_code != 200:
        print("Failed to send Kakao message:", response.text)
