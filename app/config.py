from pydantic import BaseSettings
from pathlib import Path
import logging

class Settings(BaseSettings):
    # 기본 설정
    APP_NAME: str = "모니터링 시스템 API"
    DEBUG: bool = True
    
    # 데이터베이스 설정
    DATABASE_URL: str = "sqlite:///./monitor.db"
    
    # 모니터링 설정
    MAX_WORKERS: int = 3
    MAX_TABS_PER_WORKER: int = 5
    TAB_CLEANUP_THRESHOLD: int = 3000  # 탭 정리 임계값 (초)
    CHECK_INTERVAL: int = 60  # 모니터링 체크 간격 (초)
    
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
    DRIVER_PATH: str = r"D:\save\Programs\executable\chromedriver\135.0.7023\chromedriver.exe"
    
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
    RECENT_MESSAGES_MAX: int = 50  # 최근 메시지 저장 최대 개수
    MESSAGE_EXPIRY_SECONDS: int = 3600  # 메시지 만료 시간 (초)
    
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
    MEMORY_CHECK_INTERVAL: int = 300  # 메모리 확인 간격 (초)
    MEMORY_THRESHOLD_MB: int = 500  # 메모리 정리 임계값 (MB)
    GLOBAL_CLEANUP_INTERVAL: int = 3600  # 전체 정리 간격 (초)
    
    # 탭 관리 최적화 설정
    TAB_ROTATION_THRESHOLD: int = 100  # 탭 회전 임계값 (요청 횟수)
    CACHE_CLEANUP_INTERVAL: int = 20  # 캐시 정리 간격 (요청 횟수)
    
    # 로깅 설정
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_FILE: str = "monitor.log"
    LOG_RETENTION: int = 7  # 로그 보관 일수
    LOG_BACKUP_COUNT: int = 5  # 로그 백업 파일 수
    LOG_TO_CONSOLE: bool = True  # 콘솔에 로그 출력 여부

    class Config:
        env_file = ".env"

settings = Settings()

# 로깅 설정 초기화
def setup_logging():
    logger = logging.getLogger("monitor")
    logger.setLevel(getattr(logging, settings.LOG_LEVEL))
    
    # 파일 핸들러 설정
    file_handler = logging.FileHandler(settings.LOG_FILE)
    file_handler.setFormatter(logging.Formatter(settings.LOG_FORMAT))
    logger.addHandler(file_handler)
    
    # 콘솔 핸들러 설정 (선택적)
    if settings.LOG_TO_CONSOLE:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(settings.LOG_FORMAT))
        logger.addHandler(console_handler)
    
    return logger

# 로거 인스턴스 생성
logger = setup_logging() 