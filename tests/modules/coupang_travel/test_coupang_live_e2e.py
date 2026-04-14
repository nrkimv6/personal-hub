"""쿠팡 모니터링 T4 — 실서버(localhost:8001) E2E 플로우 테스트

실제 서버가 기동된 상태에서만 의미 있다.
실서버 미기동 시 pytest.skip()으로 자동 건너뜀.

실행:
    pytest tests/modules/coupang_travel/test_coupang_live_e2e.py -m http_live -v
    pytest tests/modules/coupang_travel/test_coupang_live_e2e.py -m "http_live and destructive_live" --run-destructive-live -v
"""
import pytest
import httpx

pytestmark = [pytest.mark.http_live, pytest.mark.destructive_live]

BASE_URL = "http://localhost:8001"
COUPANG = f"{BASE_URL}/api/v1/coupang"

# 테스트용 고정 상품 URL (실제 쿠팡 여행 URL 형식)
_TEST_URL = "https://trip.coupang.com/tp/products/10000011218760"
_TEST_VIP = "test-pkg"


# ──────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────

def _skip_if_down() -> None:
    """실서버 미기동 시 테스트 skip."""
    try:
        httpx.get(BASE_URL, timeout=5)
    except httpx.ConnectError:
        pytest.fail("실서버 미기동 — localhost:8001 연결 불가")


def _create_target(name: str = "__test_live__") -> dict:
    """테스트용 쿠팡 상품 등록. 반환: {"id": int, "product_id": str}"""
    resp = httpx.post(
        f"{COUPANG}/targets",
        json={"url": _TEST_URL, "vendor_item_package_id": _TEST_VIP, "name": name},
        timeout=30,
    )
    assert resp.status_code == 201, f"target 생성 실패: {resp.status_code} {resp.text}"
    return resp.json()


def _delete_target(biz_item_id: int) -> None:
    """테스트용 상품 삭제 (teardown — 실패 무시)."""
    try:
        httpx.delete(f"{COUPANG}/targets/{biz_item_id}", timeout=30)
    except Exception:
        pass


def _create_schedule(biz_item_id: int, dates: list) -> dict:
    """테스트용 스케줄 생성. 반환: {"created": int}"""
    resp = httpx.post(
        f"{COUPANG}/schedules",
        json={"biz_item_id": biz_item_id, "dates": dates},
        timeout=30,
    )
    assert resp.status_code == 201, f"schedule 생성 실패: {resp.status_code} {resp.text}"
    return resp.json()


def _get_schedules() -> list:
    """전체 쿠팡 스케줄 목록 반환."""
    resp = httpx.get(f"{COUPANG}/schedules", timeout=30)
    assert resp.status_code == 200
    return resp.json()


# ──────────────────────────────────────────────
# Phase 1 테스트
# ──────────────────────────────────────────────

def test_live_coupang_full_flow():
    """R: 상품 등록→스케줄 생성→목록 확인→상태 조회 전체 플로우 E2E 검증."""
    _skip_if_down()
    name = "__test_e2e_full__"
    biz_item_id = None
    try:
        target = _create_target(name)
        biz_item_id = target["id"]
        assert "product_id" in target

        _create_schedule(biz_item_id, ["2026-12-31"])

        schedules = _get_schedules()
        assert any(s["item_name"] == name for s in schedules), \
            f"스케줄 목록에 {name!r} 없음. 실제: {[s['item_name'] for s in schedules]}"

        resp = httpx.get(f"{COUPANG}/status", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_schedules"] >= 1
        assert "enabled_schedules" in data
        assert "active_schedules" in data
    finally:
        if biz_item_id:
            _delete_target(biz_item_id)


def test_live_schedule_enable_disable_toggle():
    """R: 스케줄 enable→disable 상태 전환 검증."""
    _skip_if_down()
    name = "__test_toggle__"
    biz_item_id = None
    try:
        target = _create_target(name)
        biz_item_id = target["id"]

        _create_schedule(biz_item_id, ["2026-12-31"])

        schedules = _get_schedules()
        schedule_id = next(
            (s["id"] for s in schedules if s["item_name"] == name), None
        )
        assert schedule_id is not None, f"스케줄 ID 찾기 실패: {name!r}"

        # enable
        resp = httpx.post(f"{COUPANG}/schedules/{schedule_id}/enable", timeout=10)
        assert resp.status_code == 200
        assert resp.json()["is_enabled"] is True

        # disable
        resp = httpx.post(f"{COUPANG}/schedules/{schedule_id}/disable", timeout=10)
        assert resp.status_code == 200
        assert resp.json()["is_enabled"] is False
    finally:
        if biz_item_id:
            _delete_target(biz_item_id)


def test_live_cleanup_removes_past_date():
    """R: 과거 날짜 스케줄이 cleanup으로 삭제됨 확인."""
    _skip_if_down()
    name = "__test_cleanup__"
    biz_item_id = None
    try:
        target = _create_target(name)
        biz_item_id = target["id"]

        _create_schedule(biz_item_id, ["2025-01-01"])  # 과거 날짜

        pre_schedules = _get_schedules()
        assert any(s["item_name"] == name for s in pre_schedules), \
            "cleanup 전 테스트 스케줄 없음"

        resp = httpx.post(f"{COUPANG}/schedules/cleanup", timeout=10)
        assert resp.status_code == 200
        assert resp.json()["deleted"] >= 1

        post_schedules = _get_schedules()
        assert not any(s["item_name"] == name for s in post_schedules), \
            "cleanup 후 테스트 스케줄이 남아 있음"
    finally:
        if biz_item_id:
            _delete_target(biz_item_id)


def test_live_delete_target_cascades_schedules():
    """R: 상품 삭제 시 연결된 스케줄도 cascade 삭제됨."""
    _skip_if_down()
    name = "__test_cascade__"
    target = _create_target(name)
    biz_item_id = target["id"]

    _create_schedule(biz_item_id, ["2026-12-31"])

    schedules = _get_schedules()
    schedule_id = next(
        (s["id"] for s in schedules if s["item_name"] == name), None
    )
    assert schedule_id is not None, "스케줄 생성 확인 실패"

    # 상품 삭제 → cascade
    resp = httpx.delete(f"{COUPANG}/targets/{biz_item_id}", timeout=10)
    assert resp.status_code == 200

    post_schedules = _get_schedules()
    assert not any(s["id"] == schedule_id for s in post_schedules), \
        "상품 삭제 후 스케줄이 남아 있음"


def test_live_monitoring_events_hours_filter_smoke():
    """R: 운영 데이터 기준 monitoring/events hours 조회가 200과 필수 필드를 반환한다."""
    _skip_if_down()
    resp = httpx.get(
        f"{BASE_URL}/api/v1/monitoring/events",
        params={"service_type": "coupang", "status": "available", "hours": "13,18", "page_size": 20},
        timeout=30,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert "total" in body
    assert "page" in body
    assert "page_size" in body
    assert "total_pages" in body
