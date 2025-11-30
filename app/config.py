from pydantic_settings import BaseSettings
from pathlib import Path
import logging
from datetime import datetime
import sys
import os
from typing import Optional, Dict, Any, List, Set
from pydantic import Field, validator, AnyHttpUrl

# 로거 구성
logger = logging.getLogger("monitor_app")
logger.setLevel(logging.INFO)

# 콘솔 핸들러 추가
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

class Settings(BaseSettings):
    # 기본 설정
    APP_NAME: str = "모니터링 시스템 API"
    DEBUG: bool = True
    
    # 데이터베이스 설정
    DATABASE_URL: str = "sqlite:///./monitor.db"
    
    # 모니터링 설정
    MAX_WORKERS: int = 3
    MAX_TABS_PER_WORKER: int = 3
    TAB_CLEANUP_THRESHOLD: int = 3000  # 탭 정리 임계값 (초)
    CHECK_INTERVAL: int = 60  # 모니터링 체크 간격 (초)
    MAX_CONCURRENT_CHECKS: int = 5  # 동시 체크 최대 수
    
    # 날짜 기반 스케줄링 설정
    DATE_BASED_SCHEDULING: bool = True  # 날짜 기반 스케줄링 활성화 여부
    DEFAULT_SHORT_INTERVAL: tuple = (2, 7)  # 오늘/이미 지난 날짜 간격 (최소, 최대)
    DEFAULT_TOMORROW_INTERVAL: tuple = (3, 10)  # 내일 날짜 간격 (최소, 최대)
    DEFAULT_NEAR_INTERVAL: tuple = (20, 50)  # 1-7일 이내 간격 (최소, 최대)
    DEFAULT_FAR_INTERVAL: tuple = (200, 300)  # 7일 이상 간격 (최소, 최대)
    
    # 브라우저 설정
    USER_DATA_DIR: Path = Path("./browser_data")
    #r"C:\Users\Narang\AppData\Local\Google\Chrome\User Data"
    CHROME_PATH: str = r"C:\Program Files\Google\Chrome Dev\Application\chrome.exe"
    DRIVER_PATH: str = r"D:\Programs\executable\chromedriver\135.0.7023\chromedriver.exe"
    
    # # Supabase 설정
    # SUPABASE_URL: str
    # SUPABASE_KEY: str
    
    # @property
    # def supabase(self) -> Client:
    #     return create_client(self.SUPABASE_URL, self.SUPABASE_KEY)
    
    # 알림 설정
    TELEGRAM_BOT_TOKEN: str = "7912548094:AAGp1Ii05IPFpM3uec75NTzJceYwrq2Lb4g"
    TELEGRAM_CHAT_ID: str = "7774293093"
    ENABLE_DESKTOP_NOTIFICATION: bool = True
    EMAIL_ADDRESS:str = "g100mkrw1@gmail.com"
    EMAIL_PASSWORD:str = "Caww@60925"  # Gmail 앱 비밀번호
    RECIPIENT_EMAIL:str = "orangepie2236@email.com"
    
    # 중복 메시지 필터링 설정
    MESSAGE_DEDUPLICATION: bool = True  # 중복 메시지 필터링 활성화 여부
    RECENT_MESSAGES_MAX: int = 100  # 최근 메시지 저장 최대 개수
    MESSAGE_EXPIRY_SECONDS: int = 300  # 메시지 만료 시간 (초)
    
    # 에러 페이지 감지 설정
    ERROR_PAGE_DETECTION: bool = True  # 에러 페이지 감지 활성화 여부
    ERROR_PATTERNS: list = [
        "invalidBusiness",  # 매진 상태
        "error",  # 일반 에러
        "errorPage",  # 에러 페이지
        "페이지를 찾을 수 없습니다",  # 404 에러
        "서비스 점검 중입니다",  # 서비스 점검
    ]
    
    # 브라우저 리소스 관리 설정
    MEMORY_CHECK_INTERVAL: int = 60  # 메모리 확인 간격 (초)
    MEMORY_THRESHOLD_MB: int = 1000  # 메모리 정리 임계값 (MB)
    GLOBAL_CLEANUP_INTERVAL: int = 1800  # 전체 정리 간격 (초)
    
    # 탭 관리 최적화 설정
    TAB_ROTATION_THRESHOLD: int = 600  # 탭 회전 임계값 (초)
    CACHE_CLEANUP_INTERVAL: int = 300  # 캐시 정리 간격 (초)
    TAB_REQUEST_TIMEOUT: int = 60  # 탭 요청 시간 초과 (초)
    TAB_WAIT_RETRY_INTERVAL: int = 5  # 탭 요청 재시도 간격 (초)
    TOTAL_MAX_TABS: int = 5  # 전체 브라우저에서 사용할 최대 탭 수
    
    # 로깅 설정
    LOG_LEVEL: str = "DEBUG"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_FILE_PREFIX: str = "logs/monitor"
    LOG_RETENTION: int = 7  # 로그 보관 일수
    LOG_BACKUP_COUNT: int = 5  # 로그 백업 파일 수
    LOG_TO_CONSOLE: bool = True  # 콘솔에 로그 출력 여부
    LOG_ENCODING: str = "utf-8"  # 로그 파일 인코딩 방식
    
    # 로그 파일명 생성용 시작 시간 (서버 부팅 시간)
    SERVER_START_TIME: str = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 동적 로그 파일명 생성 (시작시간 포함)
    @property
    def LOG_FILE(self) -> str:
        return f"{self.LOG_FILE_PREFIX}_{self.SERVER_START_TIME}.log"

    # 모니터링 설정
    INITIAL_CHECK_DELAY: int = 2  # 초기 검사 지연 (초)
    ERROR_RETRY_DELAY: int = 30  # 오류 재시도 지연 (초)
    MAX_CONSECUTIVE_ERRORS: int = 5  # 최대 연속 오류 수
    
    # 알림 발송 설정
    NOTIFY_STATES: Set[str] = {
        "매진→예약가능",   # 매진 상태에서 예약 가능으로 변경
        "초기화",         # 처음 확인 시
        "에러발생",       # 에러 발생 시
        "에러해결"        # 에러 해결 시
    }
    
    # 항상 알림을 보낼 상태 (변화가 없어도 보냄)
    ALWAYS_NOTIFY_STATES: Set[str] = {
        "예약가능"        # 예약 가능 상태는 항상 알림
    }

    model_config = {
        "env_file": ".env",
        "case_sensitive": True
    }

settings = Settings()

# 로깅 설정 초기화
def setup_logging():
    logger.setLevel(getattr(logging, settings.LOG_LEVEL))
    
    # 기존 핸들러 제거 (재시작 시 중복 방지)
    if logger.handlers:
        logger.handlers.clear()
    
    # 파일 핸들러 설정 - UTF-8 인코딩 명시
    file_handler = logging.FileHandler(settings.LOG_FILE, encoding=settings.LOG_ENCODING)
    file_handler.setFormatter(logging.Formatter(settings.LOG_FORMAT))
    logger.addHandler(file_handler)
    
    # 콘솔 핸들러 설정 (선택적)
    if settings.LOG_TO_CONSOLE:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(settings.LOG_FORMAT))
        logger.addHandler(console_handler)
    
    # 서버 시작 로그 기록
    logger.info(f"로깅 시스템 초기화 완료 - 로그 파일: {settings.LOG_FILE} (인코딩: {settings.LOG_ENCODING})")
    logger.info(f"서버 시작 시간: {settings.SERVER_START_TIME}")
    
    return logger

# 로거 인스턴스 생성
logger = setup_logging()

# 로깅 레벨 설정
if settings.DEBUG:
    logger.setLevel(logging.DEBUG)
    console_handler.setLevel(logging.DEBUG)
    logger.debug("디버그 모드 활성화됨") 