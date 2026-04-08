"""T3 통합 TC: SSE 재연결 시 historical 라인 재전송 방지 검증.

시나리오:
  1. 로그 파일에 50라인 기록
  2. stream_events() 제너레이터 시작 (_init_tail_offsets_for_active_runners 호출됨)
  3. _runner_tail_state[id]["offset"]이 파일 EOF로 설정됐는지 확인
  4. 로그 파일에 신규 10라인 추가
  5. fallback 폴링 후 신규 10라인만 log 이벤트로 수신되는지 검증 (이전 50라인 재전송 없음)
"""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


def _make_service_for_t3(runner_id: str, log_file: Path):
    """stream_events() 초기화 + fallback 검증용 service mock."""
    from app.modules.dev_runner.services.event_service import EventService

    svc = EventService.__new__(EventService)
    svc._sync = MagicMock()
    svc._async = MagicMock()
    svc._runner_tail_state = {}
    svc._completed_runners = {}
    svc._dedup_window = 50
    svc._tail_state_ttl_sec = 300
    svc._completed_runner_ttl_sec = 300

    # _list_visible_active_runner_ids: runner_id 1개 반환
    svc._list_visible_active_runner_ids = MagicMock(return_value=[runner_id])

    # _resolve_runner_log_path: log_file 반환
    svc._resolve_runner_log_path = MagicMock(return_value=log_file)

    # _ensure_tail_state_for_path: 실제 구현 사용
    original_ensure = EventService._ensure_tail_state_for_path.__get__(svc, EventService)
    svc._ensure_tail_state_for_path = original_ensure

    # _ensure_runtime_state: 실제 구현 사용
    original_ensure_runtime = EventService._ensure_runtime_state.__get__(svc, EventService)
    svc._ensure_runtime_state = original_ensure_runtime

    # _get_or_create_tail_state: 실제 구현 사용
    original_get_or_create = EventService._get_or_create_tail_state.__get__(svc, EventService)
    svc._get_or_create_tail_state = original_get_or_create

    # _drop_tail_state
    original_drop = EventService._drop_tail_state.__get__(svc, EventService)
    svc._drop_tail_state = original_drop

    return svc


class TestStreamEventsReconnectT3:

    def test_init_offsets_called_after_connected_event(self, tmp_path, monkeypatch):
        """stream_events() 시작 시 _init_tail_offsets_for_active_runners가 호출되고
        tail offset이 파일 EOF로 설정되는지 검증.
        """
        runner_id = "test-runner-t3"
        log_file = tmp_path / f"plan-runner-{runner_id}-20260408.log"

        # 50라인 기록
        historical_lines = [f"line-{i:03d}" for i in range(50)]
        log_file.write_text("\n".join(historical_lines) + "\n", encoding="utf-8")
        initial_size = log_file.stat().st_size

        svc = _make_service_for_t3(runner_id, log_file)

        called = {"count": 0}
        original_init = svc._init_tail_offsets_for_active_runners

        async def tracked_init():
            called["count"] += 1
            await original_init()

        svc._init_tail_offsets_for_active_runners = tracked_init

        # stream_events() 제너레이터의 connected + init_offsets 부분까지만 실행
        # (이후 pub/sub 루프는 mock으로 차단)
        async def run_partial():
            # _enable_keyspace_notifications 패치
            svc._enable_keyspace_notifications = AsyncMock()
            svc._build_all_runners_status = MagicMock(return_value=[])
            svc._build_tracking_payload = MagicMock(return_value=None)
            svc._stabilize_commit_failed_status_payload = AsyncMock(side_effect=lambda rid, p: p)

            gen = svc.stream_events()
            # "event: connected" 이벤트 수신
            first = await gen.asend(None)
            assert "connected" in first

            # _init_tail_offsets_for_active_runners가 호출되도록 다음 이벤트 진행
            # (status 이벤트 직전에 호출됨)
            try:
                await gen.asend(None)
            except StopAsyncIteration:
                pass

            await gen.aclose()

        asyncio.get_event_loop().run_until_complete(run_partial())

        # 검증: _init_tail_offsets_for_active_runners 호출됨
        assert called["count"] >= 1, "_init_tail_offsets_for_active_runners가 호출되지 않음"

        # 검증: runner의 tail offset == 파일 EOF
        state = svc._runner_tail_state.get(runner_id)
        assert state is not None, f"runner_id={runner_id}의 tail_state가 없음"
        assert state["offset"] == initial_size, (
            f"tail offset이 EOF({initial_size})가 아님: {state['offset']}"
        )

    def test_fallback_reads_only_new_lines_after_offset(self, tmp_path):
        """_poll_runner_log_delta가 EOF offset 이후의 신규 라인만 반환하는지 검증.

        _init_tail_offsets_for_active_runners가 offset을 EOF로 설정한 뒤
        신규 라인 10개가 추가됐을 때, historical 라인은 재전송되지 않아야 한다.
        """
        import json
        from app.modules.dev_runner.services.event_service import EventService

        runner_id = "test-runner-fallback"
        log_file = tmp_path / f"plan-runner-{runner_id}-20260408.log"

        # 기존 50라인 기록
        historical_lines = [f"hist-{i:03d}" for i in range(50)]
        log_file.write_text("\n".join(historical_lines) + "\n", encoding="utf-8")
        initial_size = log_file.stat().st_size

        svc = _make_service_for_t3(runner_id, log_file)

        # _poll_runner_log_delta에 필요한 추가 mock
        svc._sync.get = MagicMock(return_value="user")  # trigger mock
        svc._file_poll_max_lines = 200
        svc._file_poll_max_chars = 1_000_000
        svc._is_runner_recently_completed = MagicMock(return_value=False)
        svc._mark_runner_completed = MagicMock()

        # tail state를 EOF로 직접 초기화 (init_tail_offsets 효과 재현)
        state = svc._get_or_create_tail_state(runner_id)
        state["path"] = str(log_file)
        state["inode"] = (log_file.stat().st_dev, log_file.stat().st_ino)
        state["offset"] = initial_size
        state["last_seen"] = __import__("time").monotonic()

        # 신규 10라인 추가
        new_lines = [f"new-{i:03d}" for i in range(10)]
        with log_file.open("a", encoding="utf-8") as f:
            f.write("\n".join(new_lines) + "\n")

        # _poll_runner_log_delta 호출
        events, dedup_skipped = svc._poll_runner_log_delta(runner_id=runner_id)

        # 신규 10라인만 수신되어야 함
        assert len(events) == 10, f"신규 라인 10개 기대, 실제: {len(events)}"
        for i, (event_type, data) in enumerate(events):
            assert event_type == "log", f"event_type 불일치: {event_type!r}"
            assert data.get("line") == new_lines[i], f"라인 {i} 불일치: {data.get('line')!r}"

        # 히스토리 라인(hist-*)은 없어야 함
        all_lines = [data.get("line", "") for _, data in events]
        assert not any(l.startswith("hist-") for l in all_lines), "historical 라인이 재전송됨"
