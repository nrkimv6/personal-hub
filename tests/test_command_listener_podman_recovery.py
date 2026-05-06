"""worker-command-listener.py — Podman 자동 복구 로직 테스트

테스트 대상:
1. attempt_podman_recovery() — Podman 소켓 검증 + Machine 재수립 + Redis 복구
2. main() 루프 — 연속 실패 카운터 + 쿨다운 기반 복구 트리거
"""
import subprocess
import sys
import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts" / "services"


# ============================================================
# 모듈 로드 헬퍼
# ============================================================

def _load_listener():
    """worker-command-listener.py를 모듈로 임포트한다."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "worker_command_listener",
        SCRIPTS_DIR / "worker-command-listener.py",
    )
    mod = importlib.util.module_from_spec(spec)
    # redis 의존성 미리 주입
    import redis as redis_lib
    sys.modules["worker_command_listener"] = mod
    spec.loader.exec_module(mod)
    return mod


# ============================================================
# Phase T1-7: attempt_podman_recovery() 단위 테스트
# ============================================================

class TestAttemptPodmanRecovery:
    """attempt_podman_recovery() 함수 테스트"""

    def _make_completed_process(self, returncode=0):
        p = MagicMock()
        p.returncode = returncode
        p.stderr = b""
        return p

    def test_attempt_recovery_podman_ok_returns_false(self):
        """R: podman ps 성공 → False 반환 (Podman 정상, 복구 불필요)"""
        mod = _load_listener()
        with patch("subprocess.run", return_value=self._make_completed_process(0)):
            result = mod.attempt_podman_recovery()
        assert result is False

    def test_attempt_recovery_recycle_success(self):
        """R: podman ps 실패 → machine stop/start 성공 → podman start 성공 → Redis ping 성공 → True"""
        mod = _load_listener()
        call_results = [
            self._make_completed_process(1),  # podman ps — 실패
            self._make_completed_process(0),  # machine stop
            self._make_completed_process(0),  # machine start
            self._make_completed_process(0),  # podman start monitor-redis
        ]
        mock_redis = MagicMock()
        with patch("subprocess.run", side_effect=call_results), \
             patch("time.sleep"), \
             patch("redis.Redis", return_value=mock_redis):
            mock_redis.ping.return_value = True
            result = mod.attempt_podman_recovery()
        assert result is True

    def test_attempt_recovery_recycle_fail_redis(self):
        """E: podman ps 실패 → machine stop/start 성공 → Redis ping 실패 → False"""
        mod = _load_listener()
        call_results = [
            self._make_completed_process(1),  # podman ps — 실패
            self._make_completed_process(0),  # machine stop
            self._make_completed_process(0),  # machine start
            self._make_completed_process(0),  # podman start monitor-redis
        ]
        import redis as redis_lib
        mock_redis = MagicMock()
        mock_redis.ping.side_effect = redis_lib.ConnectionError("still dead")
        with patch("subprocess.run", side_effect=call_results), \
             patch("time.sleep"), \
             patch("redis.Redis", return_value=mock_redis):
            result = mod.attempt_podman_recovery()
        assert result is False

    def test_attempt_recovery_machine_start_timeout(self):
        """E: machine start에서 TimeoutExpired → False 반환, 예외 전파 없음"""
        mod = _load_listener()

        def side_effect(args, **kwargs):
            if args == ["podman", "machine", "start"]:
                raise subprocess.TimeoutExpired(args, 60)
            return self._make_completed_process(1 if args == ["podman", "ps"] else 0)

        with patch("subprocess.run", side_effect=side_effect), \
             patch("time.sleep"):
            result = mod.attempt_podman_recovery()
        assert result is False


# ============================================================
# Phase T1-8: main 루프 복구 트리거 테스트
# ============================================================

class TestMainLoopPodmanTrigger:
    """main() 루프 내 Podman 복구 트리거 로직 테스트"""

    FIXED_NOW = 1_000_000.0  # 고정된 "현재 시각" (테스트 재현성)

    def _run_main_with_n_failures(self, mod, n_failures, last_recovery_time=0.0, recovery_result=False):
        """main() 루프에서 N회 ConnectionError를 발생시키고 attempt_podman_recovery 호출 여부를 확인한다.

        time.time()은 FIXED_NOW를 반환한다.
        last_recovery_time은 FIXED_NOW 기준 상대 오프셋이 아닌 절대값으로 설정한다.
        쿨다운 내: last_recovery_time = FIXED_NOW (경과=0)
        쿨다운 경과: last_recovery_time = 0 (경과=FIXED_NOW >> cooldown)
        """
        import redis as redis_lib

        call_count = [0]

        class FakeRedis:
            def __init__(self, **kwargs):
                pass

            def ping(self):
                call_count[0] += 1
                if call_count[0] <= n_failures:
                    raise redis_lib.ConnectionError("down")
                raise KeyboardInterrupt  # 충분히 반복 후 종료

            def close(self):
                pass

        # 모듈 레벨 상태 초기화
        mod._last_podman_recovery_time = last_recovery_time

        with patch.object(mod, "attempt_podman_recovery", return_value=recovery_result) as mock_recovery, \
             patch("redis.Redis", FakeRedis), \
             patch("time.sleep"), \
             patch("time.time", return_value=self.FIXED_NOW):
            try:
                mod.main()
            except KeyboardInterrupt:
                pass
            return mock_recovery

    def test_recovery_triggered_after_n_failures(self):
        """R: ConnectionError N회 연속 → attempt_podman_recovery 호출됨"""
        mod = _load_listener()
        threshold = mod.PODMAN_RECOVERY_THRESHOLD
        # last_recovery_time=0 → elapsed = FIXED_NOW - 0 = 1_000_000 >> cooldown
        mock_recovery = self._run_main_with_n_failures(mod, threshold, last_recovery_time=0.0)
        mock_recovery.assert_called_once()

    def test_recovery_not_triggered_below_threshold(self):
        """B: 연속 실패 N-1회 → attempt_podman_recovery 호출 안 됨"""
        mod = _load_listener()
        threshold = mod.PODMAN_RECOVERY_THRESHOLD
        mock_recovery = self._run_main_with_n_failures(mod, threshold - 1, last_recovery_time=0.0)
        mock_recovery.assert_not_called()

    def test_cooldown_prevents_retry_within_window(self):
        """B: 복구 직후 쿨다운 미경과 → 재시도 안 함"""
        mod = _load_listener()
        threshold = mod.PODMAN_RECOVERY_THRESHOLD
        # last_recovery_time = FIXED_NOW → elapsed = FIXED_NOW - FIXED_NOW = 0 < cooldown
        mock_recovery = self._run_main_with_n_failures(
            mod, threshold * 2, last_recovery_time=self.FIXED_NOW
        )
        mock_recovery.assert_not_called()

    def test_cooldown_allows_retry_after_window(self):
        """R: 쿨다운 경과(600초+) 후 → 재시도 허용"""
        mod = _load_listener()
        threshold = mod.PODMAN_RECOVERY_THRESHOLD
        # last_recovery_time = 0 → elapsed = FIXED_NOW >> cooldown
        mock_recovery = self._run_main_with_n_failures(
            mod, threshold, last_recovery_time=0.0
        )
        mock_recovery.assert_called_once()

    def test_counter_resets_on_success(self):
        """R: Redis 연결 성공(ping OK) 시 consecutive_failures = 0 리셋"""
        mod = _load_listener()
        import redis as redis_lib

        ping_call = [0]

        class FakeRedis:
            def __init__(self, **kwargs):
                pass

            def ping(self):
                ping_call[0] += 1
                if ping_call[0] == 1:
                    raise redis_lib.ConnectionError("first fail")
                if ping_call[0] == 2:
                    return True  # 성공 — consecutive_failures 리셋
                raise KeyboardInterrupt

            def close(self):
                pass

            def brpop(self, *args, **kwargs):
                raise KeyboardInterrupt

        mod._last_podman_recovery_time = 0.0
        with patch("redis.Redis", FakeRedis), \
             patch.object(mod, "attempt_podman_recovery", return_value=False) as mock_rec, \
             patch("time.sleep"), \
             patch("time.time", return_value=9999999):
            try:
                mod.main()
            except KeyboardInterrupt:
                pass
        # 1회 실패 후 성공으로 리셋 → threshold 미달로 복구 미호출
        mock_rec.assert_not_called()


# ============================================================
# Phase T3: 통합 TC
# ============================================================

@pytest.mark.integration
def test_podman_ps_subprocess_integration():
    """Integration: 실제 subprocess.run(["podman", "ps"]) 실행 — 예외 없이 완료, returncode가 int"""
    result = subprocess.run(["podman", "ps"], capture_output=True, timeout=10)
    assert isinstance(result.returncode, int), f"returncode must be int, got {type(result.returncode)}"
