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

# 프로젝트 루트 디렉토리 (.env 파일 경로 계산용)
PROJECT_ROOT = Path(__file__).parent.parent.parent

class Settings(BaseSettings):
    # 기본 설정
    APP_NAME: str = "모니터링 시스템 API"
    DEBUG: bool = True
    APP_MODE: str = "public"  # "public" | "admin"

    @validator("APP_MODE", pre=True)
    def strip_app_mode(cls, v):
        """환경변수에서 공백 제거"""
        if isinstance(v, str):
            return v.strip()
        return v
    
    # 데이터베이스 설정 (2026-04-10: SQLite → PostgreSQL 전환)
    DATABASE_URL: str = "postgresql://monitor_user:monitor_pass_2026@localhost:5432/monitor"
    
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
    
    # 데이터 디렉토리 설정
    DATA_DIR: str = "./data"  # 데이터 저장 디렉토리 (DB, 브라우저 프로필 등)

    # 브라우저 설정 (레거시 - 하위 호환성)
    USER_DATA_DIR: Path = Path("./browser_data")  # 구 버전 호환용 (deprecated)
    #r"C:\Users\Narang\AppData\Local\Google\Chrome\User Data"
    CHROME_PATH: str = r"C:\Program Files\Google\Chrome Dev\Application\chrome.exe"
    DRIVER_PATH: str = r"D:\Programs\executable\chromedriver\135.0.7023\chromedriver.exe"
    BROWSER_HEADLESS: bool = False  # 브라우저 UI 표시 여부 (False: 창 표시, True: 백그라운드)

    # 다중 프로필 설정
    BROWSER_PROFILES_DIR: str = "browser_profiles"  # DATA_DIR 하위의 프로필 디렉토리명
    DEFAULT_PROFILE_NAME: str = "default"  # 기본 프로필 이름
    
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

    # 프로세스 트리 추적 설정
    PROCESS_SCAN_INTERVAL: int = 60  # 프로세스 스캔 주기 (초)
    MEMORY_PRESSURE_CHECK_INTERVAL: int = 10  # 메모리 압박 체크 주기 (초)
    PROCESS_WATCH_STALE_SECONDS: int = 120  # 최신 스냅샷 stale 기준 (초)
    PROCESS_WATCH_ON_DEMAND_COOLDOWN_SEC: int = 30  # on-demand 캡처 최소 간격 (초)
    PROCESS_WATCH_CAPTURE_TIMEOUT_SEC: int = 10  # 주기 수집 타임아웃 (초)
    PROCESS_WATCH_CAPTURE_EVERY_LOOPS: int = 1  # N 루프마다 스냅샷 수집
    PROCESS_WATCH_RETENTION_DAYS: int = 7  # 스냅샷/감사로그 보관일
    PROCESS_WATCH_LOG_ROTATE_MB: int = 20  # JSONL 회전 크기 (MB)
    PROCESS_WATCH_CAPTURE_LIMIT: int = 200  # 1회 수집 최대 레코드 수
    MEMORY_CAUTION_MB: int = 4096   # 주의 임계값 (MB)
    MEMORY_WARNING_MB: int = 2048   # 경고 임계값 (MB)
    MEMORY_CRITICAL_MB: int = 1024  # 위험 임계값 (MB)
    MEMORY_EMERGENCY_MB: int = 512  # 긴급 임계값 (MB)
    MEMORY_FATAL_MB: int = 256      # 강제 재부팅 임계값 (MB)
    MEMORY_PRESSURE_OUTBOUND_ALERT_MAX_MB: int = 500  # 500MB 이상은 history-only, 미만만 outbound 허용

    # bizItems API 캐싱 설정 (REQ-MON-006)
    BIZ_ITEMS_CACHE_TTL_NORMAL: int = 300  # 정상 운영 시 캐시 TTL (초) - 5분
    BIZ_ITEMS_CACHE_TTL_CLOSED: int = 1800  # 비공개/운영중지 시 캐시 TTL (초) - 30분
    BIZ_ITEMS_CACHE_TTL_PAUSED: int = 300  # 일시중지 시 캐시 TTL (초) - 5분
    BIZ_ITEMS_CACHE_TTL_NOT_FOUND: int = 300  # 아이템 없음 시 캐시 TTL (초) - 모니터링 간격과 동일 (복귀 감지용)

    # GraphQL API Rate Limiting 설정
    MAX_CONCURRENT_GRAPHQL_REQUESTS: int = 5  # GraphQL API 동시 요청 제한
    MAX_CONCURRENT_ANONYMOUS: int = 10  # Anonymous 모드 동시 실행 제한
    GRAPHQL_CACHE_TTL: int = 10  # GraphQL 응답 캐시 TTL (초)
    
    # 로깅 설정
    LOG_LEVEL: str = "DEBUG"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_DIR: str = "logs"  # 로그 디렉토리
    LOG_RETENTION: int = 3  # 로그 보관 일수 (2025-12-22: 7일→3일로 변경)
    LOG_BACKUP_COUNT: int = 5  # 로그 백업 파일 수
    LOG_TO_CONSOLE: bool = True  # 콘솔에 로그 출력 여부
    LOG_ENCODING: str = "utf-8"  # 로그 파일 인코딩 방식

    # 워커 프로세스 설정 (워커는 Session 1에서 독립 관리, API에서 생성하지 않음)
    # API → Redis → Session 1 리스너 → browser-workers.ps1
    WORKER_HEALTH_CHECK_INTERVAL: int = 30  # 워커 헬스체크 간격 (초)

    # 프록시 설정 (공통)
    PROXY_ENABLED: bool = True  # 프록시 사용 여부
    PROXY_ROTATION_INTERVAL: int = 5  # 프록시 교체 주기 (요청 수)
    PROXY_MAX_ACTIVE_POOL: int = 100  # 활성 프록시 풀 최대 크기
    PROXY_CONNECTION_TIMEOUT: int = 5  # 프록시 연결 타임아웃 (초)
    PROXY_BLACKLIST_DURATION: int = 300  # 블랙리스트 유지 시간 (초)
    PROXY_FILE_CHECK_INTERVAL: int = 300  # 프록시 파일 변경 확인 간격 (초)

    # 프록시 V2 설정 (DB 기반)
    PROXY_BACKEND: str = "db"  # 프록시 백엔드 ("file" | "db")
    PROXY_MIN_SUCCESS_RATE: float = 0.5  # 최소 성공률 (0.0~1.0)
    PROXY_POOL_REFRESH_INTERVAL: int = 300  # 풀 갱신 주기 (초)
    PROXY_ADAPTIVE_TIMEOUT_ENABLED: bool = True  # 적응형 타임아웃 활성화
    PROXY_ADAPTIVE_TIMEOUT_MULTIPLIER: float = 2.0  # 평균 응답시간 배수
    PROXY_ADAPTIVE_TIMEOUT_MIN: float = 3.0  # 최소 타임아웃 (초)
    PROXY_ADAPTIVE_TIMEOUT_MAX: float = 10.0  # 최대 타임아웃 (초)
    PROXY_WEIGHTED_SELECTION: bool = True  # 가중치 기반 선택 활성화
    PROXY_VALIDATOR_TYPE: str = "naver"  # 검증기 타입 ("naver" | "httpbin")
    PROXY_MAX_RESPONSE_TIME: float = 2.0  # 최대 허용 응답시간 (초) - 초과 시 다음 풀에서 제외
    PROXY_COOLDOWN_SECONDS: float = 30.0  # 프록시 재사용 금지 시간 (초) - 2025-12-21 (10→30)
    PROXY_HIGH_FAILURE_HOURS: int = 6  # 실패율 체크 기간 (시간) - 2025-12-21
    PROXY_HIGH_FAILURE_MAX_RATE: float = 0.2  # 실패율 임계값 (이 값 이하면 제외) - 2025-12-21

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

    # Google OAuth 설정
    GOOGLE_CLIENT_ID: str = ""  # Google Cloud Console에서 발급
    GOOGLE_CLIENT_SECRET: str = ""  # Google Cloud Console에서 발급
    ADMIN_EMAIL: str = ""  # 관리자 이메일 (이 이메일만 관리자 권한)

    # JWT 설정
    JWT_SECRET: str = "change-me-in-production-use-random-string"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7일

    # 프론트엔드 URL (OAuth 콜백 후 리디렉트)
    FRONTEND_URL: str = "http://localhost:6100"

    # 백엔드 API URL (OAuth redirect_uri 생성용, Cloudflare Tunnel 사용 시 필수)
    API_BASE_URL: str = ""  # 예: "https://monitor.woory.day/api/v1"

    # Cloudflare Tunnel 설정 (선택)
    TUNNEL_ID: Optional[str] = None

    # 검색 API 설정 (Writing Source 수집용)
    NAVER_CLIENT_ID: str = ""  # 네이버 개발자 센터에서 발급
    NAVER_CLIENT_SECRET: str = ""  # 네이버 개발자 센터에서 발급
    KAKAO_REST_API_KEY: str = ""  # 카카오 개발자 센터에서 발급
    GOOGLE_SEARCH_API_KEY: str = ""  # Google Cloud Console에서 발급 (선택)
    GOOGLE_SEARCH_CSE_ID: str = ""  # Programmable Search Engine ID (선택)

    # 메가뷰티쇼 Kakao 알림 설정
    MEGABEAUTY_KAKAO_ALERT_ENABLED: bool = True
    MEGABEAUTY_KAKAO_ALERT_DATES: str = "2026-04-17"
    MEGABEAUTY_KAKAO_ALERT_ITEM_NAME_KEYWORD: str = "메가뷰티쇼"
    MEGABEAUTY_KAKAO_ALERT_ROOM_NAME: str = "소나무봇"
    MEGABEAUTY_KAKAO_ALERT_CLI_PATH: str = r"D:\work\project\tools\kakaocli-win\.venv\Scripts\kakaocli-win.exe"
    MEGABEAUTY_KAKAO_ALERT_EXPIRES_SECONDS: int = 900
    MEGABEAUTY_KAKAO_ALERT_DEDUP_TTL_SECONDS: int = 300
    MEGABEAUTY_KAKAO_ALERT_BACKLOG_THRESHOLD: int = 10
    MEGABEAUTY_KAKAO_ALERT_BACKLOG_COOLDOWN_SECONDS: int = 600

    # Activity Hub 동기화 설정
    ACTIVITY_HUB_PUSH_URL: str = "https://activity.woory.day/api/push"  # Activity Hub PUSH API URL
    ACTIVITY_HUB_SYNC_API_KEY: str = ""  # Activity Hub 동기화 API 키

    # Health Monitor 설정
    HEALTH_MONITOR_ENABLED: bool = True  # 헬스 모니터링 활성화 여부
    HEALTH_PID_CHECK_INTERVAL: int = 10  # PID+포트 체크 간격 (초)
    HEALTH_HTTP_CHECK_INTERVAL: int = 60  # HTTP 체크 간격 (초)
    HEALTH_CHECK_TIMEOUT: int = 10  # HTTP 요청 타임아웃 (초)
    HEALTH_FAILURE_THRESHOLD: int = 3  # HTTP 연속 실패 횟수
    HEALTH_RECOVERY_NOTIFY: bool = True  # 복구 시 알림
    EXTERNAL_API_URL: str = ""  # 외부 API URL (Cloudflare Tunnel)
    EXTERNAL_FRONTEND_URL: str = ""  # 외부 프론트엔드 URL (Cloudflare Tunnel)
    PID_DIR: str = ".pids"  # PID 파일 디렉토리

    # Git Repository Manager 설정
    GIT_REPOS_ALLOWED_PATHS: List[str] = ["D:\\work\\"]  # 등록 가능 기본 경로
    GIT_REPOS_AUTO_REFRESH_INTERVAL: int = 300  # 자동 상태 갱신 간격 (초)

    # Redis 설정 (Queue Migration)
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_ENABLED: bool = True  # False면 기존 SQLite 폴링 모드
    REDIS_QUEUE_PREFIX: str = "monitor"  # 큐 이름 prefix
    REDIS_CONNECTION_TIMEOUT: int = 5  # 연결 타임아웃 (초)

    model_config = {
        "env_file": str(PROJECT_ROOT / ".env"),
        "case_sensitive": True,
        "extra": "ignore"  # 알 수 없는 환경변수 무시 (다른 기능의 환경변수 등)
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
        # UTF-8 인코딩을 지원하는 스트림 생성
        console_stream = sys.stdout
        console_stream.reconfigure(encoding='utf-8') if hasattr(console_stream, 'reconfigure') else None

        console_handler = logging.StreamHandler(console_stream)
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
    # 워커에서는 async_logger에서 설정한 로거를 사용
    # monitor_worker.py에서 setup_worker_logger("worker", ...)를 호출하면 "worker_logger" 이름으로 생성됨
    logger = logging.getLogger("worker_logger")
