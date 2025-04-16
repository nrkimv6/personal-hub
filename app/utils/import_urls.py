"""
URLs 데이터를 데이터베이스에 임포트하는 스크립트

이 스크립트는 urls.py에 정의된 URL 목록을 읽어와서 데이터베이스에 저장합니다.
app/services/monitor_service.py의 MonitorService를 사용하여 데이터를 저장합니다.
"""

import asyncio
import sys
from pathlib import Path
import logging
import os

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("import_urls")

# 경로 설정 - 스크립트 실행 위치에 상관없이 정확한 경로를 설정
# 현재 파일의 절대 경로를 구함
current_file = os.path.abspath(__file__)
# 파일이 있는 디렉토리 경로 (app/)
app_dir = os.path.dirname(current_file)
# 프로젝트 루트 디렉토리 경로
root_dir = os.path.dirname(app_dir)

# 프로젝트 루트 경로를 sys.path에 추가하여 모듈 임포트가 가능하도록 함
sys.path.insert(0, root_dir)

# 필요한 모듈 임포트
try:
    from app.utils.urls import urls
    from app.services.monitor_service import MonitorService
    from app.schemas.monitor import MonitorTargetCreate
    from pydantic import HttpUrl
    logger.info("모듈 임포트 성공")
except ImportError as e:
    logger.error(f"모듈 임포트 실패: {str(e)}")
    logger.error(f"현재 경로: {os.getcwd()}")
    logger.error(f"sys.path: {sys.path}")
    sys.exit(1)

async def import_urls():
    """URLs 데이터를 데이터베이스에 임포트"""
    logger.info("URL 데이터 임포트 시작")
    
    # MonitorService 인스턴스 생성
    monitor_service = MonitorService()
    
    # 카운터 초기화
    total_urls = len(urls)
    success_count = 0
    skip_count = 0
    error_count = 0
    
    logger.info(f"총 {total_urls}개의 URL을 처리합니다.")
    
    # URLs 순회하면서 데이터베이스에 추가
    for i, url_data in enumerate(urls, 1):
        try:
            logger.info(f"[{i}/{total_urls}] URL 처리 중: {url_data['label']}")
            
            # MonitorTargetCreate 모델 생성
            target_data = MonitorTargetCreate(
                url=url_data["url"],
                base_url=url_data["base_url"],
                label=url_data["label"],
                date=url_data["date"],
                times=url_data["times"],
                category=url_data["category"],
                service_type=url_data["service_type"]
            )
            
            # 데이터베이스에 저장
            try:
                await monitor_service.create_target(target_data)
                logger.info(f"✅ URL 추가 성공: {url_data['label']}")
                success_count += 1
            except Exception as e:
                if "이미 존재하는 URL입니다" in str(e) or "이미 등록된 URL입니다" in str(e):
                    logger.info(f"⏭️ URL 스킵 (이미 존재함): {url_data['label']}")
                    skip_count += 1
                else:
                    logger.error(f"❌ URL 추가 실패: {url_data['label']} - {str(e)}")
                    error_count += 1
        except Exception as e:
            logger.error(f"❌ URL 처리 중 오류 발생: {str(e)}")
            error_count += 1
    
    # 결과 로깅
    logger.info("=" * 50)
    logger.info(f"URL 데이터 임포트 완료")
    logger.info(f"총 URL 수: {total_urls}")
    logger.info(f"성공: {success_count}")
    logger.info(f"스킵 (이미 존재): {skip_count}")
    logger.info(f"실패: {error_count}")
    logger.info("=" * 50)

if __name__ == "__main__":
    asyncio.run(import_urls()) 