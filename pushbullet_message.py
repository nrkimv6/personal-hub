import os
import json
import requests


def load_config(config_file='config.json'):
    if os.path.exists(config_file):
        with open(config_file, 'r') as f:
            return json.load(f)
    return {}


def send_message(message_content, url):
    message_title = "alert"
    content = message_content
    if url:
        content += "\\n url: " + url
    send_message_pushbullet(message_title, content)


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
