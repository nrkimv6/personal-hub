"""
쿠팡 여행상품 URL 파서
"""
import re
from typing import Dict


_PRODUCT_ID_RE = re.compile(r"trip\.coupang\.com/(?:tp/)?products/(\d+)")


def parse_coupang_url(url: str) -> Dict[str, str]:
    """쿠팡 여행상품 URL에서 product_id 추출.

    Args:
        url: 쿠팡 여행상품 URL (예: https://trip.coupang.com/tp/products/10000011218760)

    Returns:
        {"product_id": str}

    Raises:
        ValueError: URL이 쿠팡 여행상품 URL이 아닌 경우
    """
    if not url:
        raise ValueError("URL이 비어있습니다.")

    match = _PRODUCT_ID_RE.search(url)
    if not match:
        raise ValueError(f"쿠팡 여행상품 URL 형식이 아닙니다: {url!r}")

    return {"product_id": match.group(1)}
