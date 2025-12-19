"""
DEPRECATED: app.modules.naver_booking.services.url_import_service로 이동됨

이 모듈은 하위 호환성을 위해 유지됩니다.
"""
import warnings

warnings.warn(
    "app.services.url_import_service는 deprecated입니다. "
    "app.modules.naver_booking.services.url_import_service를 사용하세요.",
    DeprecationWarning,
    stacklevel=2
)

from app.modules.naver_booking.services.url_import_service import (
    UrlImportService,
    UrlImportResult,
    url_import_service,
)

# 하위 호환성 - 메서드를 함수로 사용하기 위한 래퍼
import_from_url = url_import_service.import_from_url

# validate_naver_url은 별도 유틸로 유지 (parsers.py에 있음)
from app.modules.naver_booking.utils.parsers import parse_naver_booking_url

def validate_naver_url(url: str) -> bool:
    """네이버 예약 URL 유효성 검사"""
    try:
        result = parse_naver_booking_url(url)
        return result is not None
    except Exception:
        return False

__all__ = ['import_from_url', 'validate_naver_url', 'UrlImportService', 'UrlImportResult', 'url_import_service']
