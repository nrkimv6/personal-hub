import os
import json
import time
from collections import OrderedDict
from threading import Timer

import requests


def load_config(config_file='config.json'):
    if os.path.exists(config_file):
        with open(config_file, 'r') as f:
            return json.load(f)
    return {}


class MessageSender:
    def __init__(self, expiry_time=3600):  # 기본 만료 시간은 1시간 (3600초)
        self.message_queue = OrderedDict()
        self.expiry_time = expiry_time
        self.cleanup_timer = None

    def clear_message(self,url, identifier=""):
        current_time = time.time()
        key = url
        self.message_queue[key] = {
            'content': "",
            'timestamp': current_time,
            'identifier': identifier
        }

    def send_message(self, message_content, url, identifier=""):
        message_title = "alert"
        content = message_content
        identifier = str(identifier) if identifier is not None else ""

        current_time = time.time()
        key = url

        if identifier == 'err':
            send_message_pushbullet(message_title, content)
            # 'err' 메시지도 큐에 저장하고 만료 시간을 설정
            self.message_queue[key] = {
                'content': content,
                'timestamp': current_time,
                'identifier': identifier
            }
        elif key not in self.message_queue or self.message_queue[key]['identifier'] != identifier:
            self.message_queue[key] = {
                'content': content,
                'timestamp': current_time,
                'identifier': identifier
            }
            send_message_pushbullet(message_title, content)

            # 첫 메시지가 추가되면 cleanup 타이머 시작
            if len(self.message_queue) == 1:
                self.schedule_next_cleanup()
        else:
            # identifier가 다르면 업데이트만 수행
            self.message_queue[key]['identifier'] = identifier
            self.message_queue[key]['timestamp'] = current_time
            print(f"Message for URL {url} already exists. Updating identifier to {identifier}")

    def schedule_next_cleanup(self):
        if self.cleanup_timer:
            self.cleanup_timer.cancel()

        if self.message_queue:
            oldest_message_time = min(item['timestamp'] for item in self.message_queue.values())
            time_until_expiry = (oldest_message_time + self.expiry_time) - time.time()

            if time_until_expiry > 0:
                self.cleanup_timer = Timer(time_until_expiry, self.cleanup_expired_messages)
                self.cleanup_timer.start()
            else:
                self.cleanup_expired_messages()

    def cleanup_expired_messages(self):
        current_time = time.time()
        expired_keys = [
            key for key, data in self.message_queue.items()
            if current_time - data['timestamp'] >= self.expiry_time
        ]

        for key in expired_keys:
            expired_data = self.message_queue.pop(key)
            print(f"Message expired and removed for URL: {key}")
            print(f"Expired content: {expired_data['content']}")
            print(f"Identifier: {expired_data['identifier']}")

        self.schedule_next_cleanup()

# 이전 방법 : 바로 보냄
# def send_message(message_content, url):
#     message_title = "alert"
#     content = message_content
#     if url:
#         content += "\\n url: " + url
#     send_message_pushbullet(message_title, content)


def send_message_t(title, message_content, url):
    content = message_content + (r"<br />url:" + url if url else "")
    send_message_pushbullet(title, content)


def send_message_pushbullet(message_title, message_body, config_file='config.json'):
    config = load_config(config_file)

    # Try to get API key from environment variable first, then from config file
    api_key = os.environ.get('PUSHBULLET_API_KEY') or config.get('PUSHBULLET_API_KEY')

    if not api_key:
        raise ValueError("PUSHBULLET_API_KEY not found in environment variables or config file")

    url = "https://api.pushbullet.com/v2/pushes"
    headers = {
        "Access-Token": api_key,
        "Content-Type": "application/json"
    }
    data = {
        "type": "note",
        "title": message_title,
        "body": message_body
    }

    response = requests.post(url, headers=headers, data=json.dumps(data))

    if response.status_code == 200:
        print("Message sent successfully!")
    else:
        print(f"Failed to send message. Status code: {response.status_code}")
        print(f"Response: {response.text}")

# if __name__ == "__main__":
#     # This block will only run if the script is executed directly
#     title = "Test Message"
#     body = "This is a test message sent via Pushbullet API"
#     send_message(title, body)
