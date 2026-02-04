"""
모바일 크롤링 서버 메인 애플리케이션

Galaxy S23 Ultra 상에서 실행되는 경량 FastAPI 서버로,
헤디드 브라우저를 사용하여 모바일 전용 페이지를 크롤링합니다.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from datetime import datetime
import logging
import time

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 서버 시작 시각 (가동 시간 계산용)
server_start_time = time.time()


# 브라우저 매니저 임포트
from browser import get_browser_manager, set_browser_manager
from browser.playwright_manager import PlaywrightBrowserManager


# 애플리케이션 생명주기 관리
@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 시작/종료 시 실행되는 생명주기 핸들러"""
    logger.info("모바일 크롤링 서버 시작 중...")

    # 브라우저 매니저 초기화
    browser_manager = PlaywrightBrowserManager(headless=False)
    set_browser_manager(browser_manager)

    init_success = await browser_manager.initialize()
    if init_success:
        logger.info("브라우저 매니저 초기화 성공")
    else:
        logger.warning("브라우저 매니저 초기화 실패 (Phase 1-2에서 실제 브라우저 설치 필요)")

    yield

    # 브라우저 매니저 정리
    await browser_manager.cleanup()
    logger.info("모바일 크롤링 서버 종료")


# FastAPI 앱 생성
app = FastAPI(
    title="모바일 크롤링 서버",
    description="모바일 전용 페이지 크롤링을 위한 API 서버",
    version="0.1.0",
    lifespan=lifespan
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: 프로덕션에서는 제한 필요
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
from routes import fetch_router
app.include_router(fetch_router)


@app.get("/")
async def root():
    """루트 엔드포인트"""
    return {
        "service": "Mobile Crawling Server",
        "version": "0.1.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """
    헬스체크 엔드포인트

    서버 상태, 브라우저 가용성, 가동 시간 등을 반환합니다.
    데스크톱 서버에서 주기적으로 호출하여 연결 상태를 모니터링합니다.
    """
    uptime_seconds = int(time.time() - server_start_time)

    # 브라우저 상태 확인
    browser_manager = get_browser_manager()
    browser_available = False
    browser_error = None

    if browser_manager:
        try:
            browser_available = await browser_manager.is_healthy()
        except Exception as e:
            browser_error = str(e)

    return {
        "status": "healthy",
        "server_time": datetime.now().isoformat(),
        "uptime_seconds": uptime_seconds,
        "uptime_human": format_uptime(uptime_seconds),
        "browser_available": browser_available,
        "browser_error": browser_error,
        "version": "0.1.0"
    }


def format_uptime(seconds: int) -> str:
    """
    가동 시간을 사람이 읽기 쉬운 형식으로 변환

    Args:
        seconds: 가동 시간(초)

    Returns:
        "1d 2h 3m 4s" 형식의 문자열
    """
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 or not parts:
        parts.append(f"{secs}s")

    return " ".join(parts)


if __name__ == "__main__":
    import uvicorn

    # 기본 포트 8080 (Termux에서 실행 시 권한 문제 방지)
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8080,
        reload=False,  # 모바일 환경에서는 리로드 비활성화
        log_level="info"
    )
