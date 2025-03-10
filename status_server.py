from flask import Flask, render_template_string
import json
from datetime import datetime, timedelta
import os
import threading

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
        .paused { background-color: #fff3cd; }
        .not-running { background-color: #f8d7da; }
        .url-status { margin-top: 10px; padding: 10px; background-color: #f8f9fa; border-radius: 5px; }
        h1 { color: #333; }
        .refresh-btn { padding: 10px 15px; background-color: #007bff; color: white; border: none; border-radius: 5px; cursor: pointer; }
        
        /* 상태 표시 버튼 스타일 */
        .status-indicator {
            display: inline-block;
            width: 20px;
            height: 20px;
            border-radius: 50%;
            margin-right: 10px;
            vertical-align: middle;
        }
        .status-running { background-color: #28a745; } /* 초록색 */
        .status-paused { background-color: #ffc107; } /* 노란색 */
        .status-stopped { background-color: #dc3545; } /* 빨간색 */
    </style>
</head>
<body>
    <h1>강남구 강좌 모니터링 상태</h1>
    
    <div class="status-box {{ status_class }}">
        <h2>
            <span class="status-indicator status-{{ status_color }}"></span>
            프로그램 상태: {{ status_text }}
        </h2>
        <p>프로그램 시작 시간: {{ program_start_time }}</p>
        <p>마지막 확인 시간: {{ last_check_time }} ({{ time_diff }})</p>
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

def format_datetime(date_str):
    """날짜 형식 변환: ISO -> m/d H:M:S"""
    if not date_str:
        return "없음"
    try:
        dt = datetime.fromisoformat(date_str)
        return dt.strftime('%m/%d %H:%M:%S')
    except:
        return date_str

def get_time_diff(last_time_str):
    """마지막 확인 시간과 현재 시간의 차이를 분 단위로 반환"""
    if not last_time_str:
        return "시간 정보 없음"
    try:
        last_time = datetime.fromisoformat(last_time_str)
        current_time = datetime.now()
        diff = current_time - last_time
        minutes = int(diff.total_seconds() / 60)
        return f"{minutes}분 전"
    except:
        return "계산 오류"

@app.route('/')
def index():
    # 상태 정보 불러오기
    monitoring_info = load_monitoring_status()
    
    current_time = datetime.now()
    last_check_time = None
    
    if monitoring_info["last_check_time"]:
        last_check_time = datetime.fromisoformat(monitoring_info["last_check_time"])
    
    # 상태 확인 (5분 이내: 실행 중, 5~10분: 일시 정지, 10분 이상: 종료됨)
    status_text = "중단됨"
    status_class = "not-running"
    status_color = "stopped"
    
    if last_check_time is not None:
        time_diff = current_time - last_check_time
        if time_diff < timedelta(seconds=300):  # 5분 이내
            status_text = "실행 중"
            status_class = "running"
            status_color = "running"
        elif time_diff < timedelta(seconds=600):  # 5~10분
            status_text = "일시 정지됨"
            status_class = "paused"
            status_color = "paused"
    
    # 시간 형식 변환
    formatted_start_time = format_datetime(monitoring_info["program_start_time"])
    formatted_last_check_time = format_datetime(monitoring_info["last_check_time"])
    time_diff = get_time_diff(monitoring_info["last_check_time"])
    
    return render_template_string(
        HTML_TEMPLATE,
        status_text=status_text,
        status_class=status_class,
        status_color=status_color,
        program_start_time=formatted_start_time,
        last_check_time=formatted_last_check_time,
        time_diff=time_diff,
        current_time=current_time.strftime('%m/%d %H:%M:%S'),
        url_status=monitoring_info["url_status"]
    )

def start_web_server():
    """웹 서버를 백그라운드 스레드로 시작"""
    server_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5000, debug=False), daemon=True)
    server_thread.start()
    print("웹 상태 서버가 시작되었습니다 - http://localhost:5000")
    return server_thread

# 독립 실행 시
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=False) 