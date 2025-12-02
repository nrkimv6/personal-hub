from pydantic_settings import BaseSettings
from pathlib import Path
import logging
from datetime import datetime
import sys
import os
from typing import Optional, Dict, Any, List, Set
from pydantic import Field, validator, AnyHttpUrl

# 로거 구성 - 나중에 setup_logging()에서 초기화됨
logger = logging.getLogger("monitor_app")
logger.setLevel(logging.INFO)

class Settings(BaseSettings):
    # 기본 설정
    APP_NAME: str = "모니터링 시스템 API"
    DEBUG: bool = True
    
    # 데이터베이스 설정
    DATABASE_URL: str = "sqlite:///./monitor_v2.db"  # 새 계층 구조용 DB
    
    # 모니터링 설정
    MAX_WORKERS: int = 3
    MAX_TABS_PER_WORKER: int = 5  # auto_booking_graphql.py와 동일 (기존 3)
    TAB_CLEANUP_THRESHOLD: int = 600  # 탭 정리 임계값 (초) - auto_booking_graphql.py와 동일 (기존 3000)
    CHECK_INTERVAL: int = 60  # 모니터링 체크 간격 (초)
    MAX_CONCURRENT_CHECKS: int = 5  # 동시 체크 최대 수
    MAX_USES_PER_TAB: int = 50  # 탭당 최대 사용 횟수 (신규 - auto_booking_graphql.py에서 가져옴)
    
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
    BROWSER_HEADLESS: bool = False  # 브라우저 UI 표시 여부 (False: 창 표시, True: 백그라운드)
    
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

    # bizItems API 캐싱 설정 (REQ-MON-006)
    BIZ_ITEMS_CACHE_TTL_NORMAL: int = 300  # 정상 운영 시 캐시 TTL (초) - 5분
    BIZ_ITEMS_CACHE_TTL_CLOSED: int = 1800  # 비공개/운영중지 시 캐시 TTL (초) - 30분
    BIZ_ITEMS_CACHE_TTL_PAUSED: int = 300  # 일시중지 시 캐시 TTL (초) - 5분
    
    # 로깅 설정
    LOG_LEVEL: str = "DEBUG"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_DIR: str = "logs"  # 로그 디렉토리
    LOG_RETENTION: int = 7  # 로그 보관 일수
    LOG_BACKUP_COUNT: int = 5  # 로그 백업 파일 수
    LOG_TO_CONSOLE: bool = True  # 콘솔에 로그 출력 여부
    LOG_ENCODING: str = "utf-8"  # 로그 파일 인코딩 방식

    # 워커 프로세스 설정
    WORKER_AUTO_START: bool = True  # API 서버 시작 시 워커 자동 시작 여부
    WORKER_AUTO_RESTART: bool = True  # 워커 비정상 종료 시 자동 재시작 여부
    WORKER_RESTART_DELAY: int = 5  # 워커 재시작 대기 시간 (초)
    WORKER_HEALTH_CHECK_INTERVAL: int = 30  # 워커 헬스체크 간격 (초)

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


def setup_logging(logger_name: str = "api_server", log_prefix: str = "api"):
    """
    로깅 시스템을 초기화합니다.

    Args:
        logger_name: 로거 이름 (api_server 또는 monitor_worker)
        log_prefix: 로그 파일 접두사 (api 또는 worker)

    Returns:
        설정된 로거 인스턴스
    """
    from pathlib import Path

    # 로그 디렉토리 생성
    log_dir = Path(settings.LOG_DIR)
    log_dir.mkdir(exist_ok=True)

    # 프로세스별 고유 시작 시간
    start_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"{log_prefix}_{start_time}.log"

    # 로거 가져오기
    app_logger = logging.getLogger(logger_name)
    app_logger.setLevel(getattr(logging, settings.LOG_LEVEL))

    # 기존 핸들러 제거 (재시작 시 중복 방지)
    if app_logger.handlers:
        app_logger.handlers.clear()

    # 파일 핸들러 설정 - UTF-8 인코딩 명시
    file_handler = logging.FileHandler(str(log_file), encoding=settings.LOG_ENCODING)
    file_handler.setFormatter(logging.Formatter(
        f'%(asctime)s - [{log_prefix.upper()}] %(levelname)s - %(message)s'
    ))
    app_logger.addHandler(file_handler)

    # 콘솔 핸들러 설정 (선택적)
    if settings.LOG_TO_CONSOLE:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(
            f'%(asctime)s - [{log_prefix.upper()}] %(levelname)s - %(message)s'
        ))
        app_logger.addHandler(console_handler)

    # 로거에 로그 파일 경로 저장 (나중에 참조용)
    app_logger.log_file = str(log_file)
    app_logger.start_time = start_time

    # 시작 로그 기록
    app_logger.info(f"로깅 시스템 초기화 완료 - 로그 파일: {log_file}")
    app_logger.info(f"프로세스 시작 시간: {start_time}")

    return app_logger


# 로거 초기화 - 워커 프로세스에서는 API 로거를 초기화하지 않음
# 워커는 자체적으로 async_logger를 사용하여 monitor_worker 로거를 설정함
import __main__
_is_worker = hasattr(__main__, '__file__') and 'worker' in getattr(__main__, '__file__', '')

if not _is_worker:
    # API 서버용 로거 초기화
    logger = setup_logging("api_server", "api")

    # 디버그 모드 설정
    if settings.DEBUG:
        logger.setLevel(logging.DEBUG)
        logger.debug("디버그 모드 활성화됨")
else:
    # 워커에서는 빈 로거 (나중에 async_logger에서 설정)
    logger = logging.getLogger("monitor_worker")