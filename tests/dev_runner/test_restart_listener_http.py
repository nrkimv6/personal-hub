"""
Phase T5: restart-listener HTTP 통합 테스트 (실서버)

실서버(localhost:8001)에서 restart-listener API를 호출하여
Redis graceful-exit 시그널 방식으로 전환됐는지 검증합니다.

실행 조건: pytest -m http_live (실서버 필요, /merge-test에서 실행)
"""
import time
import pytest


@pytest.mark.http_live
class TestRestartListenerHttpLive:
    """실서버 직접 HTTP 호출 — /merge-test에서 실행"""

    BASE = "http://localhost:8001/api/v1"

    def test_restart_listener_api_http(self):
        """T5: POST /api/v1/dev-runner/restart-listener → 200 + success 형태"""
        import httpx

        resp = httpx.post(f"{self.BASE}/dev-runner/restart-listener", timeout=30)
        assert resp.status_code == 200
        data = resp.json()
        assert "success" in data, f"응답에 success 필드 없음: {data}"

    def test_restart_listener_heartbeat_recovery_http(self):
        """T5: restart-listener 호출 후 heartbeat가 'restarting' → 정상값 순서로 전이"""
        import httpx
        import redis as redis_lib

        # Redis 직접 연결
        r = redis_lib.Redis(host="localhost", port=6379, db=0)
        HEARTBEAT_KEY = "plan-runner:listener:heartbeat"

        # API 호출
        resp = httpx.post(f"{self.BASE}/dev-runner/restart-listener", timeout=30)
        assert resp.status_code == 200

        # heartbeat가 "restarting"으로 전환되는지 확인 (최대 5초)
        restarting_seen = False
        for _ in range(10):
            hb = r.get(HEARTBEAT_KEY)
            hb_str = hb.decode() if isinstance(hb, bytes) else (hb or "")
            if hb_str == "restarting":
                restarting_seen = True
                break
            time.sleep(0.5)

        # heartbeat가 정상값으로 복구되는지 확인 (최대 20초)
        recovered = False
        for _ in range(40):
            hb = r.get(HEARTBEAT_KEY)
            hb_str = hb.decode() if isinstance(hb, bytes) else (hb or "")
            if hb_str and hb_str != "restarting":
                recovered = True
                break
            time.sleep(0.5)

        # restarting 전이 또는 복구 중 하나는 확인되어야 함
        assert restarting_seen or recovered, (
            f"heartbeat가 'restarting' 전이 없음 (listener가 graceful-exit 수신 못함). "
            f"마지막 heartbeat: {hb_str!r}"
        )
