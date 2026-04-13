"""T3 통합 TC: SSE 재연결 시 historical 라인 재전송 방지 검증.

시나리오:
  1. 로그 파일에 50라인 기록
  2. stream_events() 제너레이터 시작 (_init_tail_offsets_for_active_runners 호출됨)
  3. _runner_tail_state[id]["offset"]이 파일 EOF로 설정됐는지 확인
  4. 로그 파일에 신규 10라인 추가
  5. fallback 폴링 후 신규 10라인만 log 이벤트로 수신되는지 검증 (이전 50라인 재전송 없음)
"""
import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


def _make_service_for_t3(runner_id: str, log_file: Path):
    """stream_events() 초기화 + fallback 검증용 service mock."""
    from app.modules.dev_runner.services.event_service import EventService
    from app.modules.dev_runner.services.event_log_tailer import LogTailer

    svc = EventService.__new__(EventService)
    svc._sync = MagicMock()
    svc._async = MagicMock()

    # LogTailer mock/real mix
    tailer = LogTailer.__new__(LogTailer)
    tailer._sync = svc._sync
    tailer._log_file_resolver = MagicMock()
    tailer._log_file_resolver.find_current_log.return_value = log_file
    tailer._runner_tail_state = {}
    tailer._completed_runners = {}
    tailer._dedup_window = 50
    tailer._tail_state_ttl_sec = 300
    tailer._completed_runner_ttl_sec = 300
    tailer._file_poll_max_lines = 200
    tailer._file_poll_max_chars = 1_000_000

    svc._log_tailer = tailer
    svc._file_poll_timeout = 5.0
    svc._file_poll_interval_sec = 1.0

    # _list_visible_active_runner_ids: runner_id 1개 반환
    svc._list_visible_active_runner_ids = MagicMock(return_value=[runner_id])

    # LogTailer 메서드들 실제 구현 연결
    tailer.get_or_create_tail_state = LogTailer.get_or_create_tail_state.__get__(tailer, LogTailer)
    tailer.ensure_tail_state_for_path = LogTailer.ensure_tail_state_for_path.__get__(tailer, LogTailer)
    tailer.init_offsets_for_active_runners = LogTailer.init_offsets_for_active_runners.__get__(tailer, LogTailer)
    tailer.drop_tail_state = LogTailer.drop_tail_state.__get__(tailer, LogTailer)
    tailer.poll_runner_log_delta = LogTailer.poll_runner_log_delta.__get__(tailer, LogTailer)
    tailer.is_runner_recently_completed = LogTailer.is_runner_recently_completed.__get__(tailer, LogTailer)
    tailer._is_duplicate_log_line = LogTailer._is_duplicate_log_line.__get__(tailer, LogTailer)
    tailer._fingerprint_line = LogTailer._fingerprint_line.__get__(tailer, LogTailer)

    svc._ensure_log_tailer = MagicMock() # stream_events 내부에서 호출됨

    return svc


class TestStreamEventsReconnectT3:

    @pytest.mark.asyncio
    async def test_init_offsets_called_after_connected_event(self, tmp_path, monkeypatch):
        """stream_events() 시작 시 init_offsets_for_active_runners가 호출되고
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
        original_init = svc._log_tailer.init_offsets_for_active_runners

        async def tracked_init(visible_ids):
            called["count"] += 1
            await original_init(visible_ids)

        svc._log_tailer.init_offsets_for_active_runners = tracked_init

        # stream_events() 제너레이터의 connected + init_offsets 부분까지만 실행
        # (이후 pub/sub 루프는 mock으로 차단)
        async def run_partial():
            # 의존성 패치
            with patch("app.modules.dev_runner.services.event_service.build_all_runners_status", return_value=[]), \
                 patch("app.modules.dev_runner.services.event_service.build_tracking_payload", return_value=None), \
                 patch("app.modules.dev_runner.services.event_service.stabilize_commit_failed_status_payload", side_effect=lambda s, rid, p: p), \
                 patch("app.modules.dev_runner.services.event_service.sse_format", side_effect=lambda ev, p: f"event: {ev}\ndata: {p}\n\n"):

                svc._enable_keyspace_notifications = AsyncMock()
                svc._cleanup_invisible_recent_runners = MagicMock()

                gen = svc.stream_events()
                # "event: connected" 이벤트 수신
                first = await gen.asend(None)
                assert "connected" in first

                # init_offsets_for_active_runners가 호출되도록 다음 이벤트 진행
                # (status 이벤트 직전에 호출됨)
                try:
                    await gen.asend(None)
                except StopAsyncIteration:
                    pass

                await gen.aclose()

        await run_partial()

        # 검증: init_offsets_for_active_runners 호출됨
        assert called["count"] >= 1, "init_offsets_for_active_runners가 호출되지 않음"

        # 검증: runner의 tail offset == 파일 EOF
        state = svc._log_tailer._runner_tail_state.get(runner_id)
        assert state is not None, f"runner_id={runner_id}의 tail_state가 없음"
        assert state["offset"] == initial_size, (
            f"tail offset이 EOF({initial_size})가 아님: {state['offset']}"
        )

    def test_fallback_reads_only_new_lines_after_offset(self, tmp_path):
        """poll_runner_log_delta가 EOF offset 이후의 신규 라인만 반환하는지 검증.

        init_offsets_for_active_runners가 offset을 EOF로 설정한 뒤
        신규 라 10개가 추가됐을 때, historical 라인은 재전송되지 않아야 한다.
        """
        runner_id = "test-runner-fallback"
        log_file = tmp_path / f"plan-runner-{runner_id}-20260408.log"

        # 기존 50라인 기록
        historical_lines = [f"hist-{i:03d}" for i in range(50)]
        log_file.write_text("\n".join(historical_lines) + "\n", encoding="utf-8")
        initial_size = log_file.stat().st_size

        svc = _make_service_for_t3(runner_id, log_file)

        # poll_runner_log_delta에 필요한 추가 mock
        svc._sync.get.return_value = "user"  # trigger mock

        # tail state를 EOF로 직접 초기화 (init_tail_offsets 효과 재현)
        state = svc._log_tailer.get_or_create_tail_state(runner_id)
        state["path"] = str(log_file)
        state["inode"] = (log_file.stat().st_dev, log_file.stat().st_ino)
        state["offset"] = initial_size
        state["last_seen"] = __import__("time").monotonic()

        # 신규 10라인 추가
        new_lines = [f"new-{i:03d}" for i in range(10)]
        with log_file.open("a", encoding="utf-8") as f:
            f.write("\n".join(new_lines) + "\n")

        # poll_runner_log_delta 호출
        events, dedup_skipped = svc._log_tailer.poll_runner_log_delta(runner_id=runner_id)

        # 신규 10라인만 수신되어야 함
        assert len(events) == 10, f"신규 라인 10개 기대, 실제: {len(events)}"
        for i, (event_type, data) in enumerate(events):
            assert event_type == "log", f"event_type 불일치: {event_type!r}"
            assert data.get("line") == new_lines[i], f"라인 {i} 불일치: {data.get('line')!r}"

        # 히스토리 라인(hist-*)은 없어야 함
        all_lines = [data.get("line", "") for _, data in events]
        assert not any(l.startswith("hist-") for l in all_lines), "historical 라인이 재전송됨"
