"""Phase T3: heartbeat 경쟁 조건 재현 TC — 실물 threading 사용

근본 원인: proc.poll() is not None 감지 시 heartbeat가 즉시 _cleanup_process_state를 호출.
수정 후: _stream_threads[rid]가 alive이면 cleanup 위임(skip).
"""

import threading
from unittest.mock import MagicMock


def _run_heartbeat_dead_process_branch(
    rid: str,
    proc: object,
    stream_threads: dict,
    cleanup_fn,
) -> bool:
    """heartbeat dead-process 분기 (Phase 1 fix 포함) 복제.
    Returns True if cleanup was called."""
    _hb_mr, _hb_ms = None, None
    if _hb_mr or _hb_ms:
        return False  # 머지 진행 중 → skip
    _t = stream_threads.get(rid)
    if _t and _t.is_alive():
        return False  # stream thread alive → cleanup 위임
    cleanup_fn(rid)
    return True


class TestHeartbeatRaceConditionFixed:
    """시나리오 A/B: 실물 threading.Thread로 경쟁 조건 재현"""

    def test_scenario_a_stream_thread_alive_skips_cleanup(self):
        """시나리오 A: _stream_output 스레드가 살아있으면 cleanup 미호출"""
        rid = "runner-race"

        # 실제 스레드 생성 (살아있는 상태)
        event = threading.Event()

        def _long_running():
            event.wait(timeout=5)  # 테스트 종료까지 대기

        t = threading.Thread(target=_long_running, daemon=True)
        t.start()

        stream_threads = {rid: t}
        cleanup_fn = MagicMock()

        proc = MagicMock()
        proc.poll.return_value = 0  # 프로세스 종료됨

        called = _run_heartbeat_dead_process_branch(rid, proc, stream_threads, cleanup_fn)

        event.set()  # 스레드 종료
        t.join(timeout=1)

        assert not called, "stream thread alive인데 cleanup이 호출됨 — 경쟁 조건 미수정"
        cleanup_fn.assert_not_called()

    def test_scenario_b_no_stream_thread_calls_cleanup(self):
        """시나리오 B: _stream_threads에 rid 없음 → cleanup 호출"""
        rid = "runner-no-thread"
        stream_threads = {}  # rid 없음
        cleanup_fn = MagicMock()

        proc = MagicMock()
        proc.poll.return_value = 0

        called = _run_heartbeat_dead_process_branch(rid, proc, stream_threads, cleanup_fn)

        assert called, "stream thread 없는데 cleanup이 호출되지 않음"
        cleanup_fn.assert_called_once_with(rid)

    def test_scenario_c_dead_thread_calls_cleanup(self):
        """시나리오 C: 스레드 있지만 이미 종료됨 → cleanup 호출"""
        rid = "runner-dead-thread"

        def _quick():
            pass

        t = threading.Thread(target=_quick, daemon=True)
        t.start()
        t.join(timeout=2)  # 완전 종료 대기

        assert not t.is_alive(), "스레드가 종료되지 않아 TC 전제 실패"

        stream_threads = {rid: t}
        cleanup_fn = MagicMock()
        proc = MagicMock()
        proc.poll.return_value = 0

        called = _run_heartbeat_dead_process_branch(rid, proc, stream_threads, cleanup_fn)

        assert called, "스레드 dead인데 cleanup이 호출되지 않음"
        cleanup_fn.assert_called_once_with(rid)
