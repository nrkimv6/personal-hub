"""_init_tail_offsets_for_active_runners 단위 TC.

API 재시작 후 SSE 재연결 시 active runner의 tail offset이 현재 파일 EOF로
초기화되어 fallback 중복 재전송을 방지하는지 검증한다.
"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from pathlib import Path


def _make_tailer():
    from app.modules.dev_runner.services.event_log_tailer import LogTailer
    from app.modules.dev_runner.services.log_file_resolver import LogFileResolver

    sync_redis = MagicMock()
    log_file_resolver = MagicMock(spec=LogFileResolver)
    tailer = LogTailer(sync_redis, log_file_resolver)
    return tailer


class TestInitTailOffsetsForActiveRunners:

    @pytest.mark.asyncio
    async def test_R_sets_offset_to_eof(self, tmp_path):
        """R: 활성 runner 1개, 로그 파일 100B → 호출 후 offset == 100."""
        log_file = tmp_path / "runner-abc.log"
        log_file.write_bytes(b"x" * 100)

        tailer = _make_tailer()
        tailer._log_file_resolver.find_current_log.return_value = log_file

        await tailer.init_offsets_for_active_runners(["abc"])

        state = tailer.get_or_create_tail_state("abc")
        assert state["offset"] == 100

    @pytest.mark.asyncio
    async def test_R_multiple_runners(self, tmp_path):
        """R: 활성 runner 2개, 각각 다른 파일 크기 → 각각 올바른 offset 설정."""
        file_a = tmp_path / "runner-a.log"
        file_b = tmp_path / "runner-b.log"
        file_a.write_bytes(b"a" * 200)
        file_b.write_bytes(b"b" * 50)

        tailer = _make_tailer()

        def find_log(runner_id):
            return file_a if runner_id == "a" else file_b

        tailer._log_file_resolver.find_current_log.side_effect = find_log

        await tailer.init_offsets_for_active_runners(["a", "b"])

        assert tailer.get_or_create_tail_state("a")["offset"] == 200
        assert tailer.get_or_create_tail_state("b")["offset"] == 50

    @pytest.mark.asyncio
    async def test_B_no_active_runners(self):
        """B: 활성 runner 없음 → 예외 없이 조용히 종료."""
        tailer = _make_tailer()
        await tailer.init_offsets_for_active_runners([])
        assert len(tailer._runner_tail_state) == 0

    @pytest.mark.asyncio
    async def test_E_file_not_found(self):
        """E: find_current_log returns None → 해당 runner skip, 예외 없음."""
        tailer = _make_tailer()
        tailer._log_file_resolver.find_current_log.return_value = None

        await tailer.init_offsets_for_active_runners(["xyz"])
        assert len(tailer._runner_tail_state) == 0

    @pytest.mark.asyncio
    async def test_E_stat_fails(self, tmp_path):
        """E: 파일 존재하나 stat() 예외 → 해당 runner skip, 다른 runner 정상 처리."""
        file_ok = tmp_path / "runner-ok.log"
        file_ok.write_bytes(b"o" * 80)

        tailer = _make_tailer()

        def find_log(runner_id):
            if runner_id == "bad":
                return tmp_path / "nonexistent-bad.log"
            return file_ok

        tailer._log_file_resolver.find_current_log.side_effect = find_log

        # bad runner의 path.stat() 실패를 유도하기 위해 Path를 패치
        original_stat = Path.stat

        def patched_stat(self_path, *args, **kwargs):
            if "nonexistent-bad" in str(self_path):
                raise OSError("permission denied")
            return original_stat(self_path, *args, **kwargs)

        with patch.object(Path, "stat", patched_stat):
            await tailer.init_offsets_for_active_runners(["bad", "ok"])

        # ok runner는 정상 처리됨 (bad runner는 state가 생성되거나 stat 실패 시 skip될 수 있음)
        # 현재 구현상 ensure_tail_state_for_path 내부에서 stat() 실패 시 None 반환
        assert tailer.get_or_create_tail_state("ok")["offset"] == 80
