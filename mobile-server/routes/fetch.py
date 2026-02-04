"""Raw HTML 수집 API 라우터"""
from fastapi import APIRouter, HTTPException
from browser import get_browser_manager
from schemas import FetchHtmlRequest, FetchHtmlResponse
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["fetch"])


@router.post("/fetch-html", response_model=FetchHtmlResponse)
async def fetch_html(request: FetchHtmlRequest):
    """
    URL에 접근하여 렌더링된 HTML을 반환

    모바일 헤디드 브라우저를 사용하여 페이지에 접근하고,
    JavaScript 렌더링이 완료된 후의 전체 HTML을 가져옵니다.

    Args:
        request: HTML 수집 요청 (URL, 대기 조건 등)

    Returns:
        HTML, 페이지 제목, 최종 URL, 스크린샷(선택)

    Raises:
        HTTPException: 브라우저 미초기화, 페이지 접근 실패 등
    """
    browser_manager = get_browser_manager()

    if not browser_manager:
        raise HTTPException(
            status_code=503,
            detail="브라우저 매니저가 초기화되지 않았습니다"
        )

    if not browser_manager.is_initialized:
        raise HTTPException(
            status_code=503,
            detail="브라우저가 초기화되지 않았습니다"
        )

    try:
        logger.info(f"HTML 수집 요청: {request.url}")

        result = await browser_manager.fetch_html(
            url=request.url,
            wait_for_selector=request.wait_for_selector,
            wait_timeout=request.wait_timeout,
            screenshot=request.screenshot
        )

        logger.info(f"HTML 수집 완료: {request.url} (길이: {len(result['html'])})")

        return FetchHtmlResponse(**result)

    except TimeoutError as e:
        logger.error(f"타임아웃: {request.url} - {e}")
        raise HTTPException(
            status_code=504,
            detail=f"페이지 로드 타임아웃: {str(e)}"
        )

    except Exception as e:
        logger.error(f"HTML 수집 실패: {request.url} - {e}")
        raise HTTPException(
            status_code=500,
            detail=f"HTML 수집 중 오류 발생: {str(e)}"
        )
