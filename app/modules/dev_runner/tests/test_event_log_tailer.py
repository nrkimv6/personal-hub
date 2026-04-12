"""event_log_tailer 단위 테스트

LogTailer 클래스의 tail state, dedup, 완료 추적, 파일 폴링 로직 검증.
fakeredis 사용 — 실제 Redis 불필요.
"""

import asyncio
import time
import pytest
import fakeredis

from unittest.mock import MagicMock
from pathlib import Path

from app.modules.dev_runner.services.event_log_tailer import (
    LogTailer,
    MAX_FALLBACK_READ_LINES,
    COMPLETED_RUNNER_TTL_SEC,
)
from app.modules.dev_runner.services.event_routing import RUNNER_KEY_PREFIX


# ─── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def fake_sync():
    r = fakeredis.FakeRedis(decode_responses=True)
    yield r
    r.close()


def _make_log_tailer(sync_redis, find_current_log_return=None) -> LogTailer:
    """mock LogFileResolver를 주입한 LogTailer 반환"""
    mock_resolver = MagicMock()
    mock_resolver.find_current_log.return_value = find_current_log_return
    return LogTailer(sync_redis, mock_resolver)


# ─── poll_runner_log_delta ───────────────────────────────────────────────────

class TestPollRunnerLogDelta:
    def test_poll_runner_log_delta_reads_new_lines(self, fake_sync, tmp_path):
        """R: 로그 파일에 라인 추가 후 poll → 정상 반환 + offset 갱신"""
        runner_id = "poll-r01"
        log_file = tmp_path / "runner.log"
        log_file.write_text("existing line\n", encoding="utf-8")

        # 가시 runner 등록
        fake_sync.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "user")

        tailer = _make_log_tailer(fake_sync, find_current_log_return=log_file)

        # 파일 EOF로 초기화 (기존 라인 스킵)
        state = tailer.ensure_tail_state_for_path(runner_id, log_file)
        assert state is not None
        state["offset"] = log_file.stat().st_size  # EOF로 이동

        # 새 라인 추가 후 poll
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("new log line\n")

        events, dedup_skipped = tailer.poll_runner_log_delta(runner_id)

        assert len(events) >= 1
        log_events = [(name, payload) for name, payload in events if name == "log"]
        assert any(p["line"] == "new log line" for _, p in log_events)
        assert dedup_skipped == 0

    def test_poll_runner_log_delta_empty_file(self, fake_sync, tmp_path):
        """B: 빈 파일 → 빈 리스트 반환"""
        runner_id = "poll-b01"
        log_file = tmp_path / "empty.log"
        log_file.write_text("", encoding="utf-8")

        fake_sync.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "user")

        tailer = _make_log_tailer(fake_sync, find_current_log_return=log_file)
        events, dedup_skipped = tailer.poll_runner_log_delta(runner_id)

        assert events == []
        assert dedup_skipped == 0

    def test_poll_runner_log_delta_completed_sentinel(self, fake_sync, tmp_path):
        """R: LOG_COMPLETED_SENTINEL 감지 → log_completed 이벤트 반환 + runner 완료 마킹"""
        runner_id = "poll-sentinel-01"
        # 실제 sentinel 포맷
        sentinel = "__COMPLETED__"
        log_file = tmp_path / "sentinel.log"
        log_file.write_text(f"{sentinel}\n", encoding="utf-8")

        fake_sync.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "user")

        tailer = _make_log_tailer(fake_sync, find_current_log_return=log_file)
        events, _ = tailer.poll_runner_log_delta(runner_id)

        completed = [(n, p) for n, p in events if n == "log_completed"]
        assert len(completed) >= 1
        assert completed[0][1]["runner_id"] == runner_id
        assert completed[0][1]["status"] == "success"
        # 완료 마킹되어 tail state 제거
        assert runner_id not in tailer._runner_tail_state
        assert tailer.is_runner_recently_completed(runner_id)


# ─── dedup ───────────────────────────────────────────────────────────────────

class TestDedupLogLine:
    def test_is_duplicate_log_line_filters_repeated(self, fake_sync):
        """R: 동일 라인 두 번 → 두 번째는 duplicate True"""
        tailer = _make_log_tailer(fake_sync)
        runner_id = "dedup-r01"
        line = "same log line"

        first = tailer._is_duplicate_log_line(runner_id, line)
        second = tailer._is_duplicate_log_line(runner_id, line)

        assert first is False
        assert second is True

    def test_is_duplicate_log_line_window_overflow(self, fake_sync):
        """B: dedup_window 초과 시 가장 오래된 fingerprint 제거 → 재등장 허용"""
        window_size = 4
        tailer = LogTailer(fake_sync, MagicMock(), dedup_window=window_size)
        runner_id = "dedup-b01"

        # "line-0" 먼저 등록
        tailer._is_duplicate_log_line(runner_id, "line-0")

        # window_size개의 새 라인을 추가해 "line-0"를 window 밖으로 밀어냄
        for i in range(1, window_size + 1):
            tailer._is_duplicate_log_line(runner_id, f"line-new-{i}")

        # "line-0"이 window에서 밀려났으므로 duplicate 아님
        result = tailer._is_duplicate_log_line(runner_id, "line-0")
        assert result is False


# ─── mark_runner_completed / is_runner_recently_completed ────────────────────

class TestCompletionTracking:
    def test_mark_runner_completed_drops_state(self, fake_sync):
        """R: mark_runner_completed 호출 시 tail state 제거 + 완료 마킹"""
        tailer = _make_log_tailer(fake_sync)
        runner_id = "complete-r01"

        # tail state 생성
        tailer.get_or_create_tail_state(runner_id)
        assert runner_id in tailer._runner_tail_state

        tailer.mark_runner_completed(runner_id)

        assert runner_id not in tailer._runner_tail_state
        assert runner_id in tailer._completed_runners

    def test_is_runner_recently_completed_ttl(self, fake_sync):
        """B: TTL 만료 후 is_runner_recently_completed → False 반환 + 항목 제거"""
        tailer = LogTailer(fake_sync, MagicMock(), completed_runner_ttl_sec=0.01)
        runner_id = "complete-b01"

        tailer._completed_runners[runner_id] = time.monotonic() - 1.0  # 이미 만료

        result = tailer.is_runner_recently_completed(runner_id)

        assert result is False
        assert runner_id not in tailer._completed_runners


# ─── cleanup_stale_state ─────────────────────────────────────────────────────

class TestCleanupStaleState:
    def test_cleanup_stale_state_removes_invisible(self, fake_sync):
        """R: visible_runner_ids에 없는 runner → cleanup 후 tail state 제거"""
        tailer = _make_log_tailer(fake_sync)

        runner_visible = "cleanup-visible-01"
        runner_invisible = "cleanup-invisible-01"

        tailer.get_or_create_tail_state(runner_visible)
        tailer.get_or_create_tail_state(runner_invisible)

        assert runner_visible in tailer._runner_tail_state
        assert runner_invisible in tailer._runner_tail_state

        tailer.cleanup_stale_state({runner_visible})

        assert runner_visible in tailer._runner_tail_state
        assert runner_invisible not in tailer._runner_tail_state


# ─── init_offsets_for_active_runners ─────────────────────────────────────────

class TestInitOffsetsForActiveRunners:
    @pytest.mark.asyncio
    async def test_init_offsets_for_active_runners_eof(self, fake_sync, tmp_path):
        """R: 활성 runner의 로그 파일 → tail offset이 EOF(st_size)로 초기화"""
        runner_id = "init-r01"
        log_file = tmp_path / "active.log"
        log_file.write_text("existing content\n", encoding="utf-8")
        expected_size = log_file.stat().st_size

        mock_resolver = MagicMock()
        mock_resolver.find_current_log.return_value = log_file
        tailer = LogTailer(fake_sync, mock_resolver)

        await tailer.init_offsets_for_active_runners([runner_id])

        state = tailer._runner_tail_state.get(runner_id)
        assert state is not None
        assert state["offset"] == expected_size


# ─── ensure_tail_state_for_path ──────────────────────────────────────────────

class TestEnsureTailStateForPath:
    def test_ensure_tail_state_for_path_rotate(self, fake_sync, tmp_path):
        """E: inode 변경(파일 교체) → offset과 dedup fingerprint 초기화"""
        from collections import deque

        runner_id = "rotate-e01"
        log_file = tmp_path / "rotating.log"
        log_file.write_text("pre-rotate content\n", encoding="utf-8")

        tailer = _make_log_tailer(fake_sync)

        # 초기 상태 등록 (inode1)
        state = tailer.ensure_tail_state_for_path(runner_id, log_file)
        assert state is not None
        state["offset"] = 100  # 임의 offset
        old_inode = state.get("inode")

        # 파일 삭제 후 재생성 → inode 변경 시뮬레이션
        log_file.unlink()
        log_file.write_text("post-rotate content\n", encoding="utf-8")

        # 새 inode로 상태 갱신
        new_state = tailer.ensure_tail_state_for_path(runner_id, log_file)
        assert new_state is not None
        assert new_state["inode"] != old_inode
        assert new_state["offset"] == 0
