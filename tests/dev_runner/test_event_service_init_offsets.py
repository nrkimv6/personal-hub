"""_init_tail_offsets_for_active_runners 단위 TC.

API 재시작 후 SSE 재연결 시 active runner의 tail offset이 현재 파일 EOF로
초기화되어 fallback 중복 재전송을 방지하는지 검증한다.
"""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


def _make_service(runner_tail_state=None):
    from app.modules.dev_runner.services.event_service import EventService

    svc = EventService.__new__(EventService)
    svc._sync = MagicMock()
    svc._async = MagicMock()
    svc._runner_tail_state = runner_tail_state if runner_tail_state is not None else {}
    svc._completed_runners = {}
    svc._dedup_window = 50
    svc._tail_state_ttl_sec = 300
    svc._completed_runner_ttl_sec = 300
    return svc


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestInitTailOffsetsForActiveRunners:

    def test_R_sets_offset_to_eof(self, tmp_path):
        """R: 활성 runner 1개, 로그 파일 100B → 호출 후 offset == 100."""
        log_file = tmp_path / "runner-abc.log"
        log_file.write_bytes(b"x" * 100)

        svc = _make_service()
        svc._list_visible_active_runner_ids = MagicMock(return_value=["abc"])
        svc._resolve_runner_log_path = MagicMock(return_value=log_file)
        # _ensure_tail_state_for_path는 실제 구현 사용 (state dict 반환)
        # offset을 직접 삽입해 반환 흉내
        fake_state = {"path": str(log_file), "offset": 0}
        svc._ensure_tail_state_for_path = MagicMock(return_value=fake_state)

        _run(svc._init_tail_offsets_for_active_runners())

        assert fake_state["offset"] == 100

    def test_R_multiple_runners(self, tmp_path):
        """R: 활성 runner 2개, 각각 다른 파일 크기 → 각각 올바른 offset 설정."""
        file_a = tmp_path / "runner-a.log"
        file_b = tmp_path / "runner-b.log"
        file_a.write_bytes(b"a" * 200)
        file_b.write_bytes(b"b" * 50)

        svc = _make_service()
        svc._list_visible_active_runner_ids = MagicMock(return_value=["a", "b"])

        state_a = {"path": str(file_a), "offset": 0}
        state_b = {"path": str(file_b), "offset": 0}

        def resolve(runner_id):
            return file_a if runner_id == "a" else file_b

        def ensure_state(runner_id, path):
            return state_a if runner_id == "a" else state_b

        svc._resolve_runner_log_path = MagicMock(side_effect=resolve)
        svc._ensure_tail_state_for_path = MagicMock(side_effect=ensure_state)

        _run(svc._init_tail_offsets_for_active_runners())

        assert state_a["offset"] == 200
        assert state_b["offset"] == 50

    def test_B_no_active_runners(self):
        """B: 활성 runner 없음 → 예외 없이 조용히 종료."""
        svc = _make_service()
        svc._list_visible_active_runner_ids = MagicMock(return_value=[])
        svc._resolve_runner_log_path = MagicMock()
        svc._ensure_tail_state_for_path = MagicMock()

        _run(svc._init_tail_offsets_for_active_runners())

        svc._resolve_runner_log_path.assert_not_called()

    def test_E_file_not_found(self):
        """E: _resolve_runner_log_path returns None → 해당 runner skip, 예외 없음."""
        svc = _make_service()
        svc._list_visible_active_runner_ids = MagicMock(return_value=["xyz"])
        svc._resolve_runner_log_path = MagicMock(return_value=None)
        svc._ensure_tail_state_for_path = MagicMock()

        _run(svc._init_tail_offsets_for_active_runners())

        svc._ensure_tail_state_for_path.assert_not_called()

    def test_E_stat_fails(self, tmp_path):
        """E: 파일 존재하나 stat() 예외 → 해당 runner skip, 다른 runner 정상 처리."""
        file_ok = tmp_path / "runner-ok.log"
        file_ok.write_bytes(b"o" * 80)

        svc = _make_service()
        svc._list_visible_active_runner_ids = MagicMock(return_value=["bad", "ok"])

        state_ok = {"path": str(file_ok), "offset": 0}

        def resolve(runner_id):
            # bad runner: 존재하지 않는 파일 (stat() 실패 유도)
            if runner_id == "bad":
                # stat() 자체 실패를 유도하기 위해 Path 객체 반환 후 ensure_state에서 모킹
                return tmp_path / "nonexistent-bad.log"
            return file_ok

        def ensure_state(runner_id, path):
            if runner_id == "bad":
                # stat()이 실패하는 상황: stat() 모킹
                bad_state = {}
                bad_path = MagicMock(spec=Path)
                bad_path.stat.side_effect = OSError("permission denied")
                # ensure_tail_state_for_path 내부에서 stat()은 별도이므로
                # 여기서는 state를 반환하되 path.stat()가 실패하도록 한다
                # 실제로는 path 객체를 직접 모킹해 stat 실패를 유도
                return {"path": str(path), "offset": 0, "_mock_stat_fail": True}
            return state_ok

        svc._resolve_runner_log_path = MagicMock(side_effect=resolve)
        svc._ensure_tail_state_for_path = MagicMock(side_effect=ensure_state)

        # bad runner의 path.stat() 실패를 유도하기 위해 Path를 패치
        original_stat = Path.stat

        def patched_stat(self_path, *args, **kwargs):
            if "nonexistent-bad" in str(self_path):
                raise OSError("permission denied")
            return original_stat(self_path, *args, **kwargs)

        with patch.object(Path, "stat", patched_stat):
            _run(svc._init_tail_offsets_for_active_runners())

        # ok runner는 정상 처리됨
        assert state_ok["offset"] == 80
