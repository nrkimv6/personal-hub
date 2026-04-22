"""
T5: GET /api/v1/system/queue — url 필드 회귀 핀 TC

pytest.mark.http — /merge-test 단계에서 main 머지 후 실행.

목표:
  - 응답 항목의 url 필드가 /booking/{숫자}/bizes/{숫자}/items/{숫자}?startDateTime= 형식임을 핀
  - system.py:549-555 SELECT 컬럼 순서(row[10]=naver_biz_item_id, row[12]=naver_business_id, row[13]=business_type_id)
    변경 시 이 TC가 깨지도록 역패턴 assertion 포함
  - b.name에 한글이 포함된 경우에도 url 첫 path 세그먼트가 숫자인지 검증
"""
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

pytestmark = pytest.mark.http


URL_PATTERN = re.compile(
    r'^https://booking\.naver\.com/booking/\d+/bizes/\d+/items/\d+\?startDateTime='
)


def _make_mock_queue_row(
    schedule_id=430,
    date="2026-04-22",
    run_status="queued",
    error_count=0,
    last_error=None,
    last_check_time=None,
    next_run_time=None,
    interval=60,
    custom_interval=None,
    biz_item_name="올리브영 예약",
    naver_biz_item_id="6309731",
    business_name="올리브영N성수",
    naver_business_id="1630978",
    business_type_id=13,
):
    """
    system.py:543 `for i, row in enumerate(result, 1):` 에서 소비되는 fetchall row 목(tuple).
    SELECT 컬럼 순서:
      [0]=ms.id, [1]=ms.date, [2]=ms.run_status, [3]=ms.error_count, [4]=ms.last_error,
      [5]=ms.last_check_time, [6]=ms.next_run_time, [7]=ms.interval, [8]=ms.custom_interval,
      [9]=bi.name(biz_item_name), [10]=bi.biz_item_id(naver_biz_item_id),
      [11]=b.name(business_name), [12]=b.business_id(naver_business_id), [13]=b.business_type_id
    """
    return (
        schedule_id,       # [0]
        date,              # [1]
        run_status,        # [2]
        error_count,       # [3]
        last_error,        # [4]
        last_check_time,   # [5]
        next_run_time,     # [6]
        interval,          # [7]
        custom_interval,   # [8]
        biz_item_name,     # [9]
        naver_biz_item_id, # [10] ← url 합성에 사용
        business_name,     # [11]
        naver_business_id, # [12] ← url 합성에 사용
        business_type_id,  # [13] ← url 합성에 사용
    )


@pytest.fixture
def queue_client():
    """system 라우터 TestClient — DB를 mock으로 대체"""
    from fastapi import FastAPI
    from app.routes.system import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/system")
    return TestClient(app)


class TestSystemQueueUrlField:

    def test_GET_system_queue_url_matches_numeric_pattern(self, queue_client):
        """R: queued 스케줄 응답의 url이 /booking/{숫자}/bizes/{숫자}/items/{숫자}?startDateTime= 형식"""
        fake_row = _make_mock_queue_row(
            naver_biz_item_id="6309731",
            naver_business_id="1630978",
            business_type_id=13,
        )
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchall.return_value = [fake_row]

        with patch("app.routes.system.SessionLocal", return_value=mock_db):
            resp = queue_client.get("/api/v1/system/queue")

        assert resp.status_code == 200
        items = resp.json()
        assert len(items) > 0, "queue 응답 항목 없음"

        for item in items:
            url = item.get("url", "")
            assert URL_PATTERN.match(url), (
                f"url이 정규식과 불일치 (business_type_id 자리가 비숫자?): {url!r}"
            )

    def test_GET_system_queue_url_first_segment_is_digit_even_with_korean_name(self, queue_client):
        """B: b.name='올리브영N성수'이어도 url 첫 path 세그먼트는 business_type_id 숫자여야 함"""
        fake_row = _make_mock_queue_row(
            business_name="올리브영N성수",
            naver_business_id="1630978",
            business_type_id=13,
        )
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchall.return_value = [fake_row]

        with patch("app.routes.system.SessionLocal", return_value=mock_db):
            resp = queue_client.get("/api/v1/system/queue")

        assert resp.status_code == 200
        items = resp.json()
        for item in items:
            url = item.get("url", "")
            assert "올리브영N성수" not in url, f"업체명이 url에 포함됨: {url!r}"
            path_part = url.split("?")[0]
            segments = path_part.split("/")
            try:
                booking_idx = segments.index("booking")
                first_seg = segments[booking_idx + 1]
            except (ValueError, IndexError):
                pytest.fail(f"url 구조 불일치: {url!r}")
            assert first_seg.isdigit(), f"첫 path 세그먼트가 비숫자: {first_seg!r}"

    def test_GET_system_queue_url_cross_check_biz_id_in_url(self, queue_client):
        """C: url에 naver_business_id, naver_biz_item_id, business_type_id가 모두 포함됨 (역패턴 핀)"""
        business_type_id = 13
        naver_business_id = "1630978"
        naver_biz_item_id = "6309731"

        fake_row = _make_mock_queue_row(
            business_type_id=business_type_id,
            naver_business_id=naver_business_id,
            naver_biz_item_id=naver_biz_item_id,
        )
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchall.return_value = [fake_row]

        with patch("app.routes.system.SessionLocal", return_value=mock_db):
            resp = queue_client.get("/api/v1/system/queue")

        assert resp.status_code == 200
        items = resp.json()
        for item in items:
            url = item.get("url", "")
            # 역패턴: SELECT 컬럼 순서 바뀌면 이 assert 실패
            assert f"/booking/{business_type_id}/bizes/" in url, (
                f"business_type_id={business_type_id}가 url에 없음: {url!r}"
            )
            assert f"/bizes/{naver_business_id}/items/" in url, (
                f"naver_business_id={naver_business_id}가 url에 없음: {url!r}"
            )
            assert f"/items/{naver_biz_item_id}?" in url, (
                f"naver_biz_item_id={naver_biz_item_id}가 url에 없음: {url!r}"
            )

    def test_GET_system_queue_empty_returns_200_empty_list(self, queue_client):
        """E: queued 스케줄 없으면 빈 배열 반환"""
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchall.return_value = []

        with patch("app.routes.system.SessionLocal", return_value=mock_db):
            resp = queue_client.get("/api/v1/system/queue")

        assert resp.status_code == 200
        assert resp.json() == []
