"""
모바일 서버 프록시 API

데스크톱 서버가 모바일 서버의 API를 프록시하는 엔드포인트입니다.
프론트엔드는 이 API를 통해 모바일 서버에 접근합니다.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
import httpx
import logging

from ..services import MobileServerClient

logger = logging.getLogger(__name__)

router = APIRouter()

# 전역 클라이언트 인스턴스
mobile_client = MobileServerClient()


class FetchHtmlRequest(BaseModel):
    """HTML 수집 요청"""
    url: str = Field(..., description="수집할 URL")
    wait_for_selector: Optional[str] = Field(None, description="대기할 CSS 셀렉터")
    wait_timeout: int = Field(30000, description="대기 시간(밀리초)", ge=1000, le=120000)
    screenshot: bool = Field(False, description="스크린샷 캡처 여부")


class FetchHtmlResponse(BaseModel):
    """HTML 수집 응답"""
    html: str
    title: str
    final_url: str
    screenshot_base64: Optional[str] = None
    fetched_at: str


class HealthResponse(BaseModel):
    """헬스체크 응답"""
    status: str
    server_time: str
    uptime_seconds: int
    uptime_human: str
    browser_available: bool
    browser_error: Optional[str] = None
    version: str


@router.get("/health", response_model=HealthResponse)
async def mobile_health_check():
    """
    모바일 서버 헬스체크 프록시

    데스크톱 서버에서 모바일 서버의 상태를 확인합니다.
    프론트엔드에서 모바일 서버 연결 상태를 모니터링하는 데 사용됩니다.

    Returns:
        모바일 서버의 헬스 정보

    Raises:
        HTTPException: 모바일 서버 연결 실패
    """
    try:
        health_data = await mobile_client.health_check()
        return HealthResponse(**health_data)

    except httpx.ConnectError as e:
        logger.error(f"모바일 서버 연결 실패: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"모바일 서버에 연결할 수 없습니다: {str(e)}"
        )

    except httpx.TimeoutException as e:
        logger.error(f"모바일 서버 타임아웃: {e}")
        raise HTTPException(
            status_code=504,
            detail="모바일 서버 응답 타임아웃"
        )

    except Exception as e:
        logger.error(f"모바일 서버 헬스체크 실패: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"헬스체크 중 오류 발생: {str(e)}"
        )


@router.post("/fetch-html", response_model=FetchHtmlResponse)
async def fetch_html_proxy(request: FetchHtmlRequest):
    """
    Raw HTML 수집 프록시

    프론트엔드에서 받은 요청을 모바일 서버로 전달하여
    모바일 브라우저로 페이지를 렌더링하고 HTML을 가져옵니다.

    이 기능은 다음 용도로 사용됩니다:
    - 신규 크롤링 대상 등록 전 페이지 구조 분석
    - 파싱 규칙 변경 시 검증
    - 접근 장애 디버깅

    Args:
        request: HTML 수집 요청 (URL, 대기 조건 등)

    Returns:
        HTML, 페이지 제목, 최종 URL, 스크린샷(선택)

    Raises:
        HTTPException: 모바일 서버 연결 실패 또는 수집 실패
    """
    try:
        logger.info(f"Raw HTML 수집 프록시 요청: {request.url}")

        result = await mobile_client.fetch_html(
            url=request.url,
            wait_for_selector=request.wait_for_selector,
            wait_timeout=request.wait_timeout,
            screenshot=request.screenshot
        )

        return FetchHtmlResponse(**result)

    except httpx.ConnectError as e:
        logger.error(f"모바일 서버 연결 실패: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"모바일 서버에 연결할 수 없습니다: {str(e)}"
        )

    except httpx.TimeoutException as e:
        logger.error(f"모바일 서버 타임아웃: {e}")
        raise HTTPException(
            status_code=504,
            detail="모바일 서버 응답 타임아웃 (브라우저 렌더링 시간 초과)"
        )

    except httpx.HTTPStatusError as e:
        logger.error(f"모바일 서버 HTTP 에러: {e.response.status_code}")
        detail = e.response.json().get("detail", str(e)) if e.response.content else str(e)
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"모바일 서버 에러: {detail}"
        )

    except Exception as e:
        logger.error(f"HTML 수집 프록시 실패: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"HTML 수집 중 오류 발생: {str(e)}"
        )
