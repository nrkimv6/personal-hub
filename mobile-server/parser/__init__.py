"""
Parser 모듈

HTML 파싱 엔진을 제공합니다.
"""
from .base import PageParser
from .types import (
    ParseConfig,
    ParseResult,
    ParsedItem,
    AttributeConfig,
    PaginationConfig
)
from .mock_parser import MockParser

__all__ = [
    "PageParser",
    "ParseConfig",
    "ParseResult",
    "ParsedItem",
    "AttributeConfig",
    "PaginationConfig",
    "MockParser"
]
