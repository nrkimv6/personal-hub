"""쿠팡 모니터링 T5 — 실서버(localhost:8001) HTTP 개별 엔드포인트 통합 테스트

실제 서버가 기동된 상태에서만 의미 있다.
실서버 미기동 시 pytest.skip()으로 자동 건너뜀.

실행:
    pytest tests/modules/coupang_travel/test_coupang_live_http.py -m http_live -v
"""
import pytest
import httpx

pytestmark = pytest.mark.http_live

BASE_URL = "http://localhost:8001"
COUPANG = f"{BASE_URL}/api/v1/coupang"
ACCOUNTS = f"{BASE_URL}/api/v1/service-accounts"
PROFILES = f"{BASE_URL}/api/v1/profiles"

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


# ──────────────────────────────────────────────
# Phase 2-7: 상품 API 정상 응답
# ──────────────────────────────────────────────

def test_live_post_target_201():
    """R: 유효한 쿠팡 URL로 상품 등록 → 201 + id/product_id 반환."""
    _skip_if_down()
    data = None
    try:
        resp = httpx.post(
            f"{COUPANG}/targets",
            json={
                "url": _TEST_URL,
                "vendor_item_package_id": "test-pkg-201",
                "name": "__test_post_target__",
            },
            timeout=30,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert "product_id" in data
        assert data["product_id"] == "10000011218760"
    finally:
        if data and "id" in data:
            _delete_target(data["id"])


def test_live_get_targets_200():
    """R: GET /targets → 200 + JSON 리스트."""
    _skip_if_down()
    resp = httpx.get(f"{COUPANG}/targets", timeout=10)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ──────────────────────────────────────────────
# Phase 2-8: 상품 API 에러 응답
# ──────────────────────────────────────────────

def test_live_post_target_invalid_url_400():
    """E: 쿠팡 URL 아닌 URL → 400."""
    _skip_if_down()
    resp = httpx.post(
        f"{COUPANG}/targets",
        json={"url": "https://invalid.com/not-coupang", "vendor_item_package_id": "x", "name": "x"},
        timeout=30,
    )
    assert resp.status_code == 400


def test_live_delete_target_404():
    """E: 존재하지 않는 biz_item_id 삭제 → 404."""
    _skip_if_down()
    resp = httpx.delete(f"{COUPANG}/targets/999999", timeout=10)
    assert resp.status_code == 404


# ──────────────────────────────────────────────
# Phase 2-9: 스케줄 API 정상 응답
# ──────────────────────────────────────────────

def test_live_post_schedule_201():
    """R: 유효 상품에 미래 날짜 스케줄 생성 → 201 + created >= 1."""
    _skip_if_down()
    biz_item_id = None
    try:
        target = _create_target("__test_sched_201__")
        biz_item_id = target["id"]
        resp = httpx.post(
            f"{COUPANG}/schedules",
            json={"biz_item_id": biz_item_id, "dates": ["2026-12-31"]},
            timeout=30,
        )
        assert resp.status_code == 201
        assert resp.json()["created"] >= 1
    finally:
        if biz_item_id:
            _delete_target(biz_item_id)  # cascade로 스케줄도 삭제


def test_live_post_schedule_no_account_201():
    """R: service_account_id 생략(비로그인 모드) → 201, service_account_id=null."""
    _skip_if_down()
    name = "__test_sched_no_acct__"
    biz_item_id = None
    try:
        target = _create_target(name)
        biz_item_id = target["id"]
        resp = httpx.post(
            f"{COUPANG}/schedules",
            json={"biz_item_id": biz_item_id, "dates": ["2026-12-30"]},
            timeout=30,
        )
        assert resp.status_code == 201

        # 비로그인 모드 확인: service_account_id=null
        schedules = httpx.get(f"{COUPANG}/schedules", timeout=10).json()
        test_sched = next((s for s in schedules if s["item_name"] == name), None)
        assert test_sched is not None, "비로그인 모드 스케줄 없음"
        assert test_sched["service_account_id"] is None
    finally:
        if biz_item_id:
            _delete_target(biz_item_id)


# ──────────────────────────────────────────────
# Phase 2-10: 스케줄 API 에러 응답
# ──────────────────────────────────────────────

def test_live_post_schedule_invalid_biz_item_400():
    """E: 존재하지 않는 biz_item_id → 400."""
    _skip_if_down()
    resp = httpx.post(
        f"{COUPANG}/schedules",
        json={"biz_item_id": 999999, "dates": ["2026-12-31"]},
        timeout=30,
    )
    assert resp.status_code == 400


def test_live_enable_schedule_404():
    """E: 존재하지 않는 스케줄 enable → 404."""
    _skip_if_down()
    resp = httpx.post(f"{COUPANG}/schedules/999999/enable", timeout=10)
    assert resp.status_code == 404


def test_live_delete_schedule_404():
    """E: 존재하지 않는 스케줄 삭제 → 404."""
    _skip_if_down()
    resp = httpx.delete(f"{COUPANG}/schedules/999999", timeout=10)
    assert resp.status_code == 404


# ──────────────────────────────────────────────
# Phase 2-11: 상태/정리 API
# ──────────────────────────────────────────────

def test_live_get_status_200():
    """R: GET /status → 200 + 필수 필드 + int 타입."""
    _skip_if_down()
    resp = httpx.get(f"{COUPANG}/status", timeout=10)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_schedules" in data
    assert "enabled_schedules" in data
    assert "active_schedules" in data
    assert isinstance(data["total_schedules"], int)
    assert isinstance(data["enabled_schedules"], int)
    assert isinstance(data["active_schedules"], int)


def test_live_cleanup_returns_deleted_field():
    """B: POST /schedules/cleanup → 200 + deleted 필드(int) 존재."""
    _skip_if_down()
    resp = httpx.post(f"{COUPANG}/schedules/cleanup", timeout=10)
    assert resp.status_code == 200
    body = resp.json()
    assert "deleted" in body
    assert isinstance(body["deleted"], int)


# ──────────────────────────────────────────────
# Phase 3-12~15: 서비스 계정 API 쿠팡 검증
# ──────────────────────────────────────────────

def test_live_list_active_coupang_accounts():
    """R: GET /service-accounts/active?service_type=coupang → 200 + list (0건이어도 200)."""
    _skip_if_down()
    resp = httpx.get(f"{ACCOUNTS}/active", params={"service_type": "coupang"}, timeout=10)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_live_create_coupang_account_flow():
    """R: 프로필에 쿠팡 계정 생성→active 목록 확인→삭제 플로우."""
    _skip_if_down()

    profiles_resp = httpx.get(f"{PROFILES}/active", timeout=10)
    assert profiles_resp.status_code == 200
    profiles = profiles_resp.json()
    if not profiles:
        pytest.skip("활성 프로필 없음 — 계정 생성 불가")

    profile_id = profiles[0]["id"]

    # 이미 coupang 계정 있으면 skip (unique 제약)
    existing = httpx.get(
        f"{ACCOUNTS}/active", params={"service_type": "coupang"}, timeout=10
    ).json()
    existing_on_profile = [a for a in existing if a["profile_id"] == profile_id]
    if existing_on_profile:
        pytest.skip("프로필에 이미 쿠팡 계정 존재 — unique 제약으로 생성 불가")

    account_id = None
    try:
        resp = httpx.post(
            f"{PROFILES}/{profile_id}/accounts",
            json={"service_type": "coupang", "identifier": "__test_coupang__"},
            timeout=30,
        )
        assert resp.status_code == 201
        account_id = resp.json()["id"]

        active = httpx.get(
            f"{ACCOUNTS}/active", params={"service_type": "coupang"}, timeout=10
        ).json()
        assert any(a["id"] == account_id for a in active), \
            "생성된 쿠팡 계정이 active 목록에 없음"
    finally:
        if account_id:
            httpx.delete(f"{ACCOUNTS}/{account_id}", timeout=10)


def test_live_coupang_account_not_in_naver_filter():
    """B: coupang 계정 ID 집합과 naver 계정 ID 집합이 교집합 없음."""
    _skip_if_down()
    coupang_resp = httpx.get(
        f"{ACCOUNTS}/active", params={"service_type": "coupang"}, timeout=10
    )
    assert coupang_resp.status_code == 200
    coupang_ids = {a["id"] for a in coupang_resp.json()}

    naver_resp = httpx.get(
        f"{ACCOUNTS}/active", params={"service_type": "naver"}, timeout=10
    )
    assert naver_resp.status_code == 200
    naver_ids = {a["id"] for a in naver_resp.json()}

    assert coupang_ids.isdisjoint(naver_ids), \
        f"coupang/naver 계정 ID 중복: {coupang_ids & naver_ids}"
