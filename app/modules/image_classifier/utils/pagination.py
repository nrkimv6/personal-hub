"""공통 페이지네이션 유틸리티.

image_classifier 라우터에서 반복되는 페이지네이션/정렬 로직을 통합.

Usage:
    from app.modules.image_classifier.utils.pagination import (
        validate_sort,
        apply_pagination,
        paginated_response,
    )

    order_by, order_dir = validate_sort(order_by, order_dir, {"id", "name"})
    query = apply_pagination(query, params, skip, limit)
    return paginated_response(items, total, skip, limit)
"""

from __future__ import annotations


def validate_sort(
    order_by: str,
    order_dir: str,
    allowed: set[str],
    default: str = "id",
) -> tuple[str, str]:
    """정렬 파라미터 검증.

    Args:
        order_by: 클라이언트가 요청한 정렬 컬럼.
        order_dir: 클라이언트가 요청한 정렬 방향 ("asc" | "desc").
        allowed: 허용된 컬럼 이름 집합.
        default: order_by 가 허용되지 않을 때 사용할 기본 컬럼.

    Returns:
        검증된 (order_by, order_dir) 튜플.
    """
    if order_by not in allowed:
        order_by = default
    if order_dir not in {"asc", "desc"}:
        order_dir = "asc"
    return order_by, order_dir


def apply_pagination(
    query: str,
    params: dict,
    skip: int,
    limit: int,
) -> str:
    """쿼리 문자열에 LIMIT / OFFSET 절 추가.

    Args:
        query: 기존 SQL 쿼리 문자열 (ORDER BY 포함 상태).
        params: 바인딩 파라미터 딕셔너리 (in-place 수정).
        skip: 건너뛸 레코드 수 (OFFSET).
        limit: 가져올 레코드 수 (LIMIT).

    Returns:
        " LIMIT :limit OFFSET :skip" 이 추가된 쿼리 문자열.
    """
    params["limit"] = limit
    params["skip"] = skip
    return query + " LIMIT :limit OFFSET :skip"


def paginated_response(
    items: list,
    total: int,
    skip: int,
    limit: int,
) -> dict:
    """일관된 페이지네이션 응답 딕셔너리 반환.

    Args:
        items: 현재 페이지의 데이터 목록.
        total: 전체 레코드 수.
        skip: 현재 페이지의 OFFSET 값.
        limit: 페이지당 레코드 수.

    Returns:
        {items, total, skip, limit, has_more} 딕셔너리.
    """
    return {
        "items": items,
        "total": total,
        "skip": skip,
        "limit": limit,
        "has_more": skip + len(items) < total,
    }
