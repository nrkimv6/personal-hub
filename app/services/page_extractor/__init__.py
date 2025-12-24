"""Page Extractor - 페이지 유형별 내용 추출 모듈.

URL 유형에 따라 적절한 추출기를 선택하여 페이지 내용을 구조화된 형태로 추출합니다.

지원 페이지 유형:
- Google Forms
- Naver Form
- Naver Blog (PC/Mobile)
- 범용 (Fallback)
"""

from .base import BaseExtractor, ExtractedContent
from .factory import ExtractorFactory
from .generic import GenericExtractor

__all__ = [
    "BaseExtractor",
    "ExtractedContent",
    "ExtractorFactory",
    "GenericExtractor",
]
