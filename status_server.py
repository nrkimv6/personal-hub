from flask import Flask, render_template_string
import json
from datetime import datetime, timedelta
import os

# Flask 앱 생성
app = Flask(__name__)

# 웹 페이지 HTML 템플릿
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>강남구 강좌 모니터링 상태</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .status-box { border: 1px solid #ddd; padding: 15px; margin-bottom: 20px; border-radius: 5px; }
        .running { background-color: #d4edda; }
        .not-running { background-color: #f8d7da; }
        .url-status { margin-top: 10px; padding: 10px; background-color: #f8f9fa; border-radius: 5px; }
        h1 { color: #333; }
        .refresh-btn { padding: 10px 15px; background-color: #007bff; color: white; border: none; border-radius: 5px; cursor: pointer; }
    </style>
</head>
<body>
    <h1>강남구 강좌 모니터링 상태</h1>
    
    <div class="status-box {{ 'running' if is_running else 'not-running' }}">
        <h2>프로그램 상태: {{ "실행 중" if is_running else "중단됨" }}</h2>
        <p>프로그램 시작 시간: {{ program_start_time }}</p>
        <p>마지막 확인 시간: {{ last_check_time }}</p>
        <p>현재 시간: {{ current_time }}</p>
    </div>
    
    <h2>강좌 상태</h2>
    {% for url, status in url_status.items() %}
    <div class="url-status">
        <p><strong>강좌 ID:</strong> {{ url }}</p>
        <p><strong>상태:</strong> {{ status }}</p>
    </div>
    {% endfor %}
    
    <button class="refresh-btn" onclick="location.reload()">새로고침</button>
</body>
</html>
'''

def load_monitoring_status():
    """모니터링 상태 JSON 파일 읽기"""
    try:
        if os.path.exists('monitoring_status.json'):
            with open('monitoring_status.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            return {
                "program_start_time": None,
                "last_check_time": None,
                "url_status": {}
            }
    except Exception as e:
        print(f"상태 파일 읽기 실패: {e}")
        return {
            "program_start_time": None,
            "last_check_time": None,
            "url_status": {}
        }

@app.route('/')
def index():
    # 상태 정보 불러오기
    monitoring_info = load_monitoring_status()
    
    current_time = datetime.now()
    last_check_time = None
    
    if monitoring_info["last_check_time"]:
        last_check_time = datetime.fromisoformat(monitoring_info["last_check_time"])
    
    # 10분(600초) 이내에 업데이트가 있었는지 확인
    is_running = last_check_time is not None and \
                (current_time - last_check_time) < timedelta(seconds=600)
    
    return render_template_string(
        HTML_TEMPLATE,
        is_running=is_running,
        program_start_time=monitoring_info["program_start_time"] or "알 수 없음",
        last_check_time=monitoring_info["last_check_time"] or "없음",
        current_time=current_time.strftime('%Y-%m-%d %H:%M:%S'),
        url_status=monitoring_info["url_status"]
    )

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=False) 