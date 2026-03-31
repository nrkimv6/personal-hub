"""
tests/log_viewer/test_follower.py — follower.py 단위 테스트 (Phase T1)

FileTailer, MultiTailer, RunnerWatcher, _detect_level, _is_error_line, _apply_filters
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.log_viewer.config import CLEANUP_FILTER_PATTERN
from app.log_viewer.follower import (
    FileTailer,
    LogLine,
    MultiTailer,
    RunnerWatcher,
    _apply_filters,
    _detect_level,
    _is_error_line,
)
from app.log_viewer.runner import RunnerInfo


# ---------------------------------------------------------------------------
# FileTailer — 파일 추적
# ---------------------------------------------------------------------------


class TestFileTailer:
    def test_file_tailer_reads_new_lines(self, tmp_path: Path):
        """R(Right): 파일에 줄을 추가하면 새 줄만 반환한다."""
        f = tmp_path / "test.log"
        f.write_text("existing line\n", encoding="utf-8")

        tailer = FileTailer(f)

        # 첫 번째 추가 (3줄)
        with f.open("a", encoding="utf-8") as fh:
            fh.write("line1\nline2\nline3\n")

        result = tailer.read_new_lines()
        assert result == ["line1", "line2", "line3"]

        # 두 번째 추가 (2줄)
        with f.open("a", encoding="utf-8") as fh:
            fh.write("line4\nline5\n")

        result2 = tailer.read_new_lines()
        assert result2 == ["line4", "line5"]

    def test_file_tailer_empty_on_no_change(self, tmp_path: Path):
        """B(Boundary): 파일 변경 없이 read_new_lines() → 빈 리스트."""
        f = tmp_path / "test.log"
        f.write_text("some content\n", encoding="utf-8")

        tailer = FileTailer(f)
        result = tailer.read_new_lines()
        assert result == []

    def test_file_tailer_skips_existing_content(self, tmp_path: Path):
        """B(Boundary): 기존 10줄 파일로 생성 → 기존 내용 스킵, 이후 추가분만 반환."""
        f = tmp_path / "test.log"
        f.write_text("\n".join(f"old{i}" for i in range(10)) + "\n", encoding="utf-8")

        tailer = FileTailer(f)
        assert tailer.read_new_lines() == []

        with f.open("a", encoding="utf-8") as fh:
            fh.write("new_line\n")

        result = tailer.read_new_lines()
        assert result == ["new_line"]

    def test_file_tailer_handles_file_rotation(self, tmp_path: Path):
        """E(Error): 파일 삭제 후 재생성(rotation) 시 새 파일 전체 내용 반환."""
        f = tmp_path / "test.log"
        f.write_text("original\n", encoding="utf-8")

        tailer = FileTailer(f)
        # 기존 내용 읽기 시뮬레이션
        with f.open("a", encoding="utf-8") as fh:
            fh.write("added\n")
        tailer.read_new_lines()

        # Rotation: 파일 삭제 후 재생성 (더 작은 크기)
        f.unlink()
        f.write_text("rotated_line\n", encoding="utf-8")

        result = tailer.read_new_lines()
        assert result == ["rotated_line"]

    def test_file_tailer_file_not_found(self, tmp_path: Path):
        """E(Error): 존재하지 않는 경로로 FileTailer 생성 → _pos=0, read_new_lines() → 빈 리스트."""
        f = tmp_path / "nonexistent.log"
        tailer = FileTailer(f)
        assert tailer._pos == 0
        assert tailer.read_new_lines() == []

    def test_file_tailer_utf8_with_errors(self, tmp_path: Path):
        """Co(Conformance): 유효하지 않은 바이트 → replacement character(\ufffd) 포함."""
        f = tmp_path / "test.log"
        # "valid\n", 깨진 바이트 "\n", "normal\n"
        f.write_bytes(b"valid\n\xff\xfe broken\nnormal\n")

        tailer = FileTailer(f)
        # 기존 내용을 스킵하지 않도록 _pos=0 강제 설정
        tailer._pos = 0

        result = tailer.read_new_lines()
        assert len(result) == 3
        assert result[0] == "valid"
        assert "\ufffd" in result[1]  # replacement character
        assert result[2] == "normal"


# ---------------------------------------------------------------------------
# MultiTailer — 다중 소스
# ---------------------------------------------------------------------------


class TestMultiTailer:
    def test_multi_tailer_add_remove_source(self, tmp_path: Path):
        """R(Right): 소스 추가 후 양쪽에서 LogLine 수신, 소스 제거 후 해당 소스 미수신."""
        path_a = tmp_path / "a.log"
        path_b = tmp_path / "b.log"
        path_a.write_text("", encoding="utf-8")
        path_b.write_text("", encoding="utf-8")

        tailer = MultiTailer()
        tailer.add_source("A", path_a, "cyan")
        tailer.add_source("B", path_b, "green")

        with path_a.open("a", encoding="utf-8") as fh:
            fh.write("msg_a\n")
        with path_b.open("a", encoding="utf-8") as fh:
            fh.write("msg_b\n")

        lines = tailer.poll_once()
        sources = {ln.source for ln in lines}
        assert "A" in sources
        assert "B" in sources

        tailer.remove_source("B")
        with path_b.open("a", encoding="utf-8") as fh:
            fh.write("msg_b2\n")

        lines2 = tailer.poll_once()
        assert all(ln.source != "B" for ln in lines2)

    def test_multi_tailer_error_only_filter(self, tmp_path: Path):
        """R(Right): error_only=True → ERROR 줄만 반환, INFO 줄 필터됨."""
        path = tmp_path / "fe.log"
        path.write_text("", encoding="utf-8")

        tailer = MultiTailer()
        tailer.add_source("FE", path, "green", error_only=True)

        with path.open("a", encoding="utf-8") as fh:
            fh.write("INFO starting\nERROR something failed\n")

        lines = tailer.poll_once()
        assert len(lines) == 1
        assert lines[0].source == "FE"
        assert "ERROR" in lines[0].text

    def test_multi_tailer_poll_no_sources(self):
        """B(Boundary): 소스 미등록 상태에서 poll_once() → 빈 리스트."""
        tailer = MultiTailer()
        assert tailer.poll_once() == []

    def test_multi_tailer_cleanup_filter(self, tmp_path: Path):
        """R(Right): cleanup=True → [cleanup] 패턴 매칭 줄만 반환."""
        path = tmp_path / "test.log"
        path.write_text("", encoding="utf-8")

        tailer = MultiTailer(cleanup=True)
        tailer.add_source("SRC", path, "white")

        with path.open("a", encoding="utf-8") as fh:
            fh.write("normal line\n[cleanup] stale runner removed\nforce_cleanup called\n")

        lines = tailer.poll_once()
        assert len(lines) == 2
        texts = [ln.text for ln in lines]
        assert any("[cleanup]" in t for t in texts)
        assert any("force_cleanup" in t for t in texts)

    def test_multi_tailer_duplicate_add_ignored(self, tmp_path: Path):
        """B(Boundary): 같은 name으로 add_source() 2회 → 첫 번째 tailer 유지."""
        path1 = tmp_path / "a.log"
        path2 = tmp_path / "b.log"
        path1.write_text("", encoding="utf-8")
        path2.write_text("", encoding="utf-8")

        tailer = MultiTailer()
        tailer.add_source("SRC", path1, "cyan")
        tailer.add_source("SRC", path2, "green")  # 중복 — 무시

        with path1.open("a", encoding="utf-8") as fh:
            fh.write("from_first\n")
        with path2.open("a", encoding="utf-8") as fh:
            fh.write("from_second\n")

        lines = tailer.poll_once()
        texts = [ln.text for ln in lines]
        assert "from_first" in texts
        assert "from_second" not in texts


# ---------------------------------------------------------------------------
# RunnerWatcher — Redis 동적 관리
# ---------------------------------------------------------------------------


def _make_runner(runner_id: str, hex_id: str = "abcd1234", log_path: str | None = None, stream_path: str | None = None) -> RunnerInfo:
    """RunnerInfo 팩토리 헬퍼. log_path가 없으면 hex_id로 표준 파일명 생성."""
    if log_path is None:
        log_path = f"/fake/plan-runner-{hex_id}-20260101-120000.log"
    return RunnerInfo(
        runner_id=runner_id,
        log_path=log_path,
        stream_path=stream_path,
        plan_file=None,
        pid=None,
    )


class TestRunnerWatcher:
    def test_runner_watcher_adds_new_runner(self, tmp_path: Path):
        """R(Right): 신규 runner 발견 시 tailer.add_source() 호출됨."""
        log_path = str(tmp_path / "plan-runner-abcd1234-20260101-120000.log")
        Path(log_path).write_text("", encoding="utf-8")

        runner = _make_runner("rid1", log_path=log_path)
        tailer = MagicMock(spec=MultiTailer)

        with patch("app.log_viewer.follower.get_active_runners", return_value=[runner]):
            watcher = RunnerWatcher()
            watcher.refresh(tailer)

        tailer.add_source.assert_called()
        call_names = [c.args[0] for c in tailer.add_source.call_args_list]
        assert any(name.startswith("PR:") for name in call_names)

    def test_runner_watcher_grace_period(self):
        """B(Boundary): runner 부재 → grace 시작, 30초 미경과 → remove 미호출, 30초 경과 → remove 호출."""
        runner = _make_runner("rid1")
        tailer = MagicMock(spec=MultiTailer)

        # _last_refresh=0.0 이므로, now > 10.0 이어야 첫 refresh가 통과됨
        # times: [0.0, 11.0, 22.0, 52.0] → 각 refresh 호출 시의 monotonic 반환값
        times = [0.0, 11.0, 22.0, 52.0]
        time_iter = iter(times)

        with patch("app.log_viewer.follower.get_active_runners") as mock_runners, \
             patch("time.monotonic", side_effect=lambda: next(time_iter)):

            watcher = RunnerWatcher()

            # 1차: t=0.0, _last_refresh=-inf처럼 초기화 필요 → 직접 설정
            watcher._last_refresh = -1000.0

            # 1차: t=0.0, runner 존재 → known에 추가
            mock_runners.return_value = [runner]
            watcher.refresh(tailer)
            assert "rid1" in watcher._known_runners

            # 2차: t=11.0, runner 부재 → grace 시작
            mock_runners.return_value = []
            watcher.refresh(tailer)
            assert "rid1" in watcher._stale_tracker
            grace_start = watcher._stale_tracker["rid1"][1]

            # 3차: t=22.0, grace 경과 11초 < 30초 → remove 미호출
            watcher.refresh(tailer)
            tailer.remove_source.assert_not_called()

            # 4차: t=52.0, grace 경과 52.0-11.0=41초 >= 30초 → remove 호출
            watcher.refresh(tailer)
            tailer.remove_source.assert_called()

    def test_runner_watcher_revival_cancels_grace(self):
        """B(Boundary): runner 부재→grace 등록 후 복귀 → grace 취소, remove 미호출."""
        runner = _make_runner("rid1")
        tailer = MagicMock(spec=MultiTailer)

        # 각 refresh 호출 시의 monotonic 반환값
        times = [0.0, 11.0, 22.0, 55.0]
        time_iter = iter(times)

        with patch("app.log_viewer.follower.get_active_runners") as mock_runners, \
             patch("time.monotonic", side_effect=lambda: next(time_iter)):

            watcher = RunnerWatcher()
            watcher._last_refresh = -1000.0  # 첫 refresh 강제 통과

            # 1차: t=0.0, runner 존재
            mock_runners.return_value = [runner]
            watcher.refresh(tailer)

            # 2차: t=11.0, runner 부재 → grace 시작
            mock_runners.return_value = []
            watcher.refresh(tailer)
            assert "rid1" in watcher._stale_tracker

            # 3차: t=22.0, runner 복귀 → grace 취소
            mock_runners.return_value = [runner]
            watcher.refresh(tailer)
            assert "rid1" not in watcher._stale_tracker

            # 4차: t=55.0, runner 다시 부재 (새 grace 시작 → remove 미호출)
            mock_runners.return_value = []
            watcher.refresh(tailer)
            tailer.remove_source.assert_not_called()

    def test_runner_watcher_respects_refresh_interval(self):
        """T(Time): 10초 미경과 시 get_active_runners 재호출 없음, 경과 시 호출."""
        tailer = MagicMock(spec=MultiTailer)

        # 첫 refresh: t=0.0에서 _last_refresh=-1000.0 → 통과, _last_refresh=0.0으로 업데이트
        # 두 번째: t=5.0, 5.0-0.0=5.0 < 10.0 → 스킵
        # 세 번째: t=15.0, 15.0-0.0=15.0 ≥ 10.0 → 통과
        times = [0.0, 5.0, 15.0]
        time_iter = iter(times)

        with patch("app.log_viewer.follower.get_active_runners") as mock_runners, \
             patch("time.monotonic", side_effect=lambda: next(time_iter)):

            mock_runners.return_value = []
            watcher = RunnerWatcher()
            watcher._last_refresh = -1000.0  # 첫 refresh 강제 통과

            watcher.refresh(tailer)  # t=0.0 → 호출됨 (count=1)
            watcher.refresh(tailer)  # t=5.0 → 10초 미경과, 스킵 (count=1)
            assert mock_runners.call_count == 1

            watcher.refresh(tailer)  # t=15.0 → 10초 경과, 호출됨 (count=2)
            assert mock_runners.call_count == 2

    def test_runner_watcher_redis_failure_graceful(self):
        """E(Error): get_active_runners → 빈 리스트(Redis 장애) → 예외 없이 정상 완료."""
        tailer = MagicMock(spec=MultiTailer)

        with patch("app.log_viewer.follower.get_active_runners", return_value=[]):
            watcher = RunnerWatcher()
            watcher.refresh(tailer)  # 예외 발생하면 실패
        # 아무 예외 없이 통과하면 성공


# ---------------------------------------------------------------------------
# _detect_level / _is_error_line / _apply_filters
# ---------------------------------------------------------------------------


class TestDetectLevel:
    def test_detect_level_error(self):
        """R(Right): ERROR 키워드 → "ERROR"."""
        assert _detect_level("2026-03-31 10:00:00 ERROR something failed") == "ERROR"

    def test_detect_level_warning(self):
        """R(Right): WARN 키워드 → "WARN"."""
        assert _detect_level("WARN: disk full") == "WARN"

    def test_detect_level_info_debug(self):
        """R(Right): INFO/DEBUG 감지."""
        assert _detect_level("INFO starting service") == "INFO"
        assert _detect_level("DEBUG trace value=42") == "DEBUG"

    def test_detect_level_none(self):
        """B(Boundary): 레벨 키워드 없는 줄 → None."""
        assert _detect_level("plain text without level") is None

    def test_detect_level_critical(self):
        """R(Right): CRITICAL → "CRITICAL"."""
        assert _detect_level("CRITICAL system failure") == "CRITICAL"


class TestIsErrorLine:
    def test_is_error_line_matches_ps1_patterns(self):
        """R(Right): PS1 $errorOnlySources 패턴 각각 매칭."""
        assert _is_error_line("ERROR occurred")
        assert _is_error_line("CRITICAL failure")
        assert _is_error_line("Exception in thread main")
        assert _is_error_line("something fail")
        assert _is_error_line("ERR_CONNECTION_REFUSED")
        assert _is_error_line("TypeError: undefined is not a function")
        assert _is_error_line("Traceback (most recent call last):")

    def test_is_error_line_normal_line(self):
        """B(Boundary): 일반 INFO 줄 → False."""
        assert not _is_error_line("INFO: normal operation completed")


class TestApplyFilters:
    def test_apply_filters_error_only_blocks_normal(self):
        """R(Right): error_only=True, 일반 줄 → False."""
        assert _apply_filters("INFO line", error_only=True, cleanup_pattern=None) is False

    def test_apply_filters_error_only_passes_error(self):
        """R(Right): error_only=True, ERROR 줄 → True."""
        assert _apply_filters("ERROR line", error_only=True, cleanup_pattern=None) is True

    def test_apply_filters_cleanup_uses_config_pattern(self):
        """R(Right): cleanup_pattern으로 CLEANUP_FILTER_PATTERN 사용 시 매칭 여부."""
        assert _apply_filters("[cleanup] done", error_only=False, cleanup_pattern=CLEANUP_FILTER_PATTERN) is True
        assert _apply_filters("normal line", error_only=False, cleanup_pattern=CLEANUP_FILTER_PATTERN) is False

    def test_apply_filters_both_flags(self):
        """C(Cross-check): error_only=True + cleanup_pattern 동시 적용 — error_only가 먼저."""
        # cleanup 매칭이지만 error가 아님 → False (error_only 먼저 평가)
        assert _apply_filters("[cleanup] done", error_only=True, cleanup_pattern=CLEANUP_FILTER_PATTERN) is False
        # error이면서 cleanup 매칭 → True
        assert _apply_filters("ERROR [cleanup] failed", error_only=True, cleanup_pattern=CLEANUP_FILTER_PATTERN) is True
