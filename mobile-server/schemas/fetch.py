"""Raw HTML 수집 API 스키마"""
from pydantic import BaseModel, Field, HttpUrl
from typing import Optional


class FetchHtmlRequest(BaseModel):
    """HTML 수집 요청 스키마"""

    url: str = Field(
        ...,
        description="수집할 페이지의 URL",
        examples=["https://example.com"]
    )
    wait_for_selector: Optional[str] = Field(
        None,
        description="대기할 CSS 셀렉터 (해당 요소가 나타날 때까지 대기)",
        examples=["#content", ".main-container"]
    )
    wait_timeout: int = Field(
        30000,
        description="최대 대기 시간 (밀리초)",
        ge=1000,
        le=120000
    )
    screenshot: bool = Field(
        False,
        description="스크린샷 캡처 여부"
    )


class FetchHtmlResponse(BaseModel):
    """HTML 수집 응답 스키마"""

    html: str = Field(
        ...,
        description="페이지의 전체 HTML"
    )
    title: str = Field(
        ...,
        description="페이지 제목"
    )
    final_url: str = Field(
        ...,
        description="리다이렉트 후 최종 URL"
    )
    screenshot_base64: Optional[str] = Field(
        None,
        description="Base64 인코딩된 스크린샷 (PNG)"
    )
    fetched_at: str = Field(
        ...,
        description="수집 시각 (ISO 8601)"
    )
