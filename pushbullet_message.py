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

    def send_message(self, message_content, url=None):
        message_title = "alert"
        content = message_content
        if url:
            content += f"\nurl: {url}"

        current_time = time.time()
        if content not in self.message_queue:
            self.message_queue[content] = current_time
            send_message_pushbullet(message_title, content)

            # 첫 메시지가 추가되면 cleanup 타이머 시작
            if len(self.message_queue) == 1:
                self.schedule_next_cleanup()


    def schedule_next_cleanup(self):
        if self.cleanup_timer:
            self.cleanup_timer.cancel()

        if self.message_queue:
            oldest_message_time = next(iter(self.message_queue.values()))
            time_until_expiry = (oldest_message_time + self.expiry_time) - time.time()

            if time_until_expiry > 0:
                self.cleanup_timer = Timer(time_until_expiry, self.cleanup_expired_messages)
                self.cleanup_timer.start()
            else:
                self.cleanup_expired_messages()

    def cleanup_expired_messages(self):
        current_time = time.time()
        expired_messages = [
            content for content, timestamp in self.message_queue.items()
            if current_time - timestamp >= self.expiry_time
        ]

        for content in expired_messages:
            del self.message_queue[content]
            print(f"Message expired and removed: {content}")

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
