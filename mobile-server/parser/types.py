"""
파싱 타입 정의

ParseConfig, ParseResult 등 파싱에 사용되는 데이터 구조를 정의합니다.
"""
from typing import Dict, Any, Optional, List, Literal
from pydantic import BaseModel, Field


class AttributeConfig(BaseModel):
    """속성 추출 설정"""
    selector: str = Field(..., description="CSS 셀렉터")
    type: Literal["text", "attr"] = Field("text", description="추출 타입 (텍스트 또는 속성)")
    attr: Optional[str] = Field(None, description="type='attr'일 때 추출할 속성명 (예: href, src)")


class PaginationConfig(BaseModel):
    """페이지네이션 설정"""
    type: Literal["url", "scroll"] = Field(..., description="페이지네이션 타입")
    selector: Optional[str] = Field(None, description="다음 페이지 링크 셀렉터")
    max_pages: int = Field(10, description="최대 수집 페이지 수")


class ParseConfig(BaseModel):
    """파싱 설정"""
    version: str = Field("1.0", description="설정 버전")
    container_selector: str = Field(..., description="아이템 컨테이너 셀렉터")
    attributes: Dict[str, AttributeConfig] = Field(..., description="속성별 추출 규칙")
    pagination: Optional[PaginationConfig] = Field(None, description="페이지네이션 설정")


class ParsedItem(BaseModel):
    """파싱된 아이템"""
    title: str = Field("", description="아이템 제목")
    item_url: Optional[str] = Field(None, description="아이템 상세 URL")
    image_url: Optional[str] = Field(None, description="이미지 URL")
    attributes: Dict[str, Any] = Field(default_factory=dict, description="추가 속성들")
    raw_html: Optional[str] = Field(None, description="원본 HTML (디버깅용)")


class ParseResult(BaseModel):
    """파싱 결과"""
    items: List[ParsedItem] = Field(default_factory=list, description="추출된 아이템 목록")
    total_count: int = Field(0, description="총 아이템 수")
    pages_crawled: int = Field(1, description="크롤링한 페이지 수")
    errors: List[str] = Field(default_factory=list, description="발생한 에러 목록")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="추가 메타데이터")
