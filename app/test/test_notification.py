import sys
import os

# 상위 디렉토리를 모듈 검색 경로에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.notification_service import NotificationService
from datetime import datetime, timedelta
import asyncio

async def test_notification():
    print("알림 서비스 기능 테스트 시작...")
    
    # NotificationService 인스턴스 생성
    notification_service = NotificationService()
    
    # 5분 30초 전 시간 생성
    last_check_time = datetime.now() - timedelta(minutes=5, seconds=30)
    print(f"마지막 확인 시간: {last_check_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 샘플 콘텐츠
    sample_content = """
    <html>
        <body>
            <h1>테스트 페이지</h1>
            <button>14:00 (3매)</button>
            <button>15:30 (1매)</button>
        </body>
    </html>
    """
    
    # 알림 테스트
    print("알림 발송 테스트...")
    await notification_service.notify_change(
        target_id=1, 
        url="https://example.com/test", 
        label="테스트 알림", 
        content=sample_content,
        last_check_time=last_check_time
    )
    
    print("알림 테스트 완료")

if __name__ == "__main__":
    asyncio.run(test_notification()) 