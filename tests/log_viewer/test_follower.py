"""
tests/log_viewer/test_follower.py — follower.py 단위 테스트 (Phase T1)

FileTailer, MultiTailer, RunnerWatcher, _detect_level, _is_error_line, _apply_filters
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.log_viewer.config import CLEANUP_FILTER_PATTERN, get_sources
from app.log_viewer.follower import (
    FileTailer,
    LogLine,
    MultiTailer,
    RunnerWatcher,
    StaticSourceWatcher,
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


# ---------------------------------------------------------------------------
# FileTailer.initial_tail TC (Phase T1 — Phase 1 대응)
# ---------------------------------------------------------------------------


class TestFileTailerInitialTail:
    def test_file_tailer_R_initial_tail_returns_existing_lines(self, tmp_path: Path):
        """R: 5줄 기록된 파일에 initial_tail=3 → 첫 read_new_lines()에서 마지막 3줄 반환."""
        f = tmp_path / "log.log"
        f.write_text("a\nb\nc\nd\ne\n", encoding="utf-8")

        tailer = FileTailer(f, initial_tail=3)
        result = tailer.read_new_lines()
        assert result == ["c", "d", "e"]

    def test_file_tailer_R_initial_tail_then_new_lines(self, tmp_path: Path):
        """R: initial_tail 3줄 반환 후, 신규 추가한 2줄을 다음 호출에서 반환 (이중 반환 없음)."""
        f = tmp_path / "log.log"
        f.write_text("old1\nold2\nold3\n", encoding="utf-8")

        tailer = FileTailer(f, initial_tail=2)
        first = tailer.read_new_lines()
        assert first == ["old2", "old3"]

        with f.open("a", encoding="utf-8") as fh:
            fh.write("new1\nnew2\n")

        second = tailer.read_new_lines()
        assert second == ["new1", "new2"]

        third = tailer.read_new_lines()
        assert third == []

    def test_file_tailer_B_initial_tail_zero_skips_existing(self, tmp_path: Path):
        """B: initial_tail=0(기본)이면 기존 줄 무시 (회귀 방어)."""
        f = tmp_path / "log.log"
        f.write_text("existing\n", encoding="utf-8")

        tailer = FileTailer(f, initial_tail=0)
        result = tailer.read_new_lines()
        assert result == []

    def test_file_tailer_B_initial_tail_larger_than_file(self, tmp_path: Path):
        """B: 파일 줄 수(2) < initial_tail(10) → 가용한 모든 줄 반환."""
        f = tmp_path / "log.log"
        f.write_text("line1\nline2\n", encoding="utf-8")

        tailer = FileTailer(f, initial_tail=10)
        result = tailer.read_new_lines()
        assert result == ["line1", "line2"]

    def test_file_tailer_E_initial_tail_on_missing_file(self, tmp_path: Path):
        """E: 미존재 파일에 initial_tail 전달 → _initial_buffer 빈 채로 생성, 예외 없음."""
        f = tmp_path / "nonexistent.log"
        tailer = FileTailer(f, initial_tail=5)
        assert tailer._initial_buffer == []
        assert tailer.read_new_lines() == []


# ---------------------------------------------------------------------------
# MultiTailer.add_source replace TC (Phase T1 — Phase 2 대응)
# ---------------------------------------------------------------------------


class TestMultiTailerReplace:
    def test_multi_tailer_R_replace_true_overwrites_entry(self, tmp_path: Path):
        """R: 같은 name으로 replace=True 호출 → 새 path의 FileTailer로 교체됨."""
        file_a = tmp_path / "a.log"
        file_b = tmp_path / "b.log"
        file_a.write_text("old\n", encoding="utf-8")
        file_b.write_text("", encoding="utf-8")

        tailer = MultiTailer()
        tailer.add_source("SRC", file_a, "cyan")
        # file_b로 교체
        tailer.add_source("SRC", file_b, "cyan", replace=True)

        # file_b에 줄 추가 → tailer가 감지해야 함
        with file_b.open("a", encoding="utf-8") as fh:
            fh.write("new_line\n")

        lines = tailer.poll_once()
        assert any(ln.text == "new_line" for ln in lines)

    def test_multi_tailer_B_replace_false_keeps_existing(self, tmp_path: Path):
        """B: replace=False(기본) → 기존 entry 유지 (회귀 방어)."""
        file_a = tmp_path / "a.log"
        file_b = tmp_path / "b.log"
        file_a.write_text("", encoding="utf-8")
        file_b.write_text("", encoding="utf-8")

        tailer = MultiTailer()
        tailer.add_source("SRC", file_a, "cyan")
        tailer.add_source("SRC", file_b, "cyan", replace=False)  # 무시됨

        # file_b에 줄 추가해도 감지 안 됨 (여전히 file_a를 follow 중)
        with file_b.open("a", encoding="utf-8") as fh:
            fh.write("from_b\n")

        lines = tailer.poll_once()
        assert not any(ln.text == "from_b" for ln in lines)


# ---------------------------------------------------------------------------
# StaticSourceWatcher TC (Phase T1 — Phase 3 대응)
# ---------------------------------------------------------------------------


class TestStaticSourceWatcher:
    def _make_source(self, name: str, prefix: str, tail_lines: int = 5):
        """테스트용 LogSource 생성 헬퍼."""
        from app.log_viewer.config import LogSource
        return LogSource(
            name=name,
            patterns=[prefix],
            color="cyan",
            tail_lines=tail_lines,
            admin_only=False,
            check_stale=True,
            error_only=False,
        )

    def test_static_watcher_R_first_refresh_immediate(self, tmp_path: Path):
        """R: 생성 직후 첫 refresh 호출이 즉시 실행됨 (_last_refresh = -inf)."""
        src = self._make_source("TST", "tst_")
        watcher = StaticSourceWatcher([src], [tmp_path])
        assert watcher._last_refresh == -float("inf")

        tailer = MultiTailer()
        log_file = tmp_path / f"tst_{time.strftime('%Y%m%d')}_000000.log"
        log_file.write_text("hello\n", encoding="utf-8")

        # 첫 호출 즉시 실행 확인 — 10초 기다릴 필요 없음
        watcher.refresh(tailer)
        assert "TST" in tailer._sources

    def test_static_watcher_R_initial_no_file_then_appears(self, tmp_path: Path, monkeypatch):
        """R: 시작 시 파일 없음 → 파일 생성 후 refresh → tailer에 add_source 호출됨."""
        from app.log_viewer import follower as follower_mod
        src = self._make_source("TST2", "tst2_")
        watcher = StaticSourceWatcher([src], [tmp_path])

        tailer = MultiTailer()
        # 첫 refresh: 파일 없음 → 등록 안 됨
        watcher.refresh(tailer)
        assert "TST2" not in tailer._sources

        # 강제로 _last_refresh를 리셋하여 throttle 우회
        watcher._last_refresh = -float("inf")

        # 오늘 날짜 파일 생성
        from datetime import date
        today_str = date.today().strftime("%Y%m%d")
        log_file = tmp_path / f"tst2_{today_str}_120000.log"
        log_file.write_text("boot_line\n", encoding="utf-8")

        watcher.refresh(tailer)
        assert "TST2" in tailer._sources

    def test_static_watcher_R_idempotent_known_path(self, tmp_path: Path):
        """R: 같은 path가 두 번 발견돼도 add_source 1회만 (mock spy)."""
        from datetime import date
        today_str = date.today().strftime("%Y%m%d")
        log_file = tmp_path / f"tst3_{today_str}_000000.log"
        log_file.write_text("data\n", encoding="utf-8")

        src = self._make_source("TST3", "tst3_")
        watcher = StaticSourceWatcher([src], [tmp_path])
        tailer = MultiTailer()

        calls = []
        orig = tailer.add_source
        tailer.add_source = lambda *a, **kw: (calls.append(a[0]), orig(*a, **kw))  # type: ignore[method-assign]

        watcher.refresh(tailer)
        first_count = len(calls)

        watcher._last_refresh = -float("inf")
        watcher.refresh(tailer)

        # 두 번째 refresh에서 same path → add_source 재호출 없음
        assert len(calls) == first_count

    def test_static_watcher_R_path_change_replaces(self, tmp_path: Path):
        """R: 어제 파일 → 오늘 파일로 갱신 → tailer.add_source(replace=True) 호출됨."""
        from datetime import date, timedelta
        today = date.today()
        yesterday = today - timedelta(days=1)
        today_str = today.strftime("%Y%m%d")
        yesterday_str = yesterday.strftime("%Y%m%d")

        # 어제 파일 (non-stale mock용 — is_stale을 monkeypatch로 제어하기 어려우므로
        # 오늘 날짜 파일 두 개로 대리)
        file_old = tmp_path / f"tstp_{today_str}_100000.log"
        file_new = tmp_path / f"tstp_{today_str}_110000.log"
        file_old.write_text("old data\n", encoding="utf-8")
        file_new.write_text("", encoding="utf-8")

        src = self._make_source("TSTP", "tstp_")
        watcher = StaticSourceWatcher([src], [tmp_path])
        tailer = MultiTailer()

        watcher.refresh(tailer)
        first_path = watcher._known_paths.get("TSTP")

        # 새 파일 갱신 (더 최근 mtime)
        import time as _time
        _time.sleep(0.01)
        file_new.write_text("newer data\n", encoding="utf-8")

        watcher._last_refresh = -float("inf")
        watcher.refresh(tailer)
        second_path = watcher._known_paths.get("TSTP")

        # path가 바뀌었어야 함
        assert first_path != second_path

    def test_static_watcher_B_throttled_within_interval(self, tmp_path: Path):
        """B: 첫 refresh 후 interval 내 재호출 → no-op."""
        from datetime import date
        today_str = date.today().strftime("%Y%m%d")
        log_file = tmp_path / f"tst5_{today_str}_000000.log"
        log_file.write_text("data\n", encoding="utf-8")

        src = self._make_source("TST5", "tst5_")
        watcher = StaticSourceWatcher([src], [tmp_path])
        tailer = MultiTailer()

        watcher.refresh(tailer)  # 첫 호출 — 등록

        # _REFRESH_INTERVAL을 100초로 강제
        watcher._REFRESH_INTERVAL = 100.0
        watcher._last_refresh = __import__("time").monotonic()

        calls = []
        orig = tailer.add_source
        tailer.add_source = lambda *a, **kw: (calls.append(a[0]), orig(*a, **kw))  # type: ignore[method-assign]

        watcher.refresh(tailer)  # throttle → no-op
        assert len(calls) == 0

    def test_static_watcher_B_stale_file_skipped(self, tmp_path: Path):
        """B: is_stale=True인 어제 파일만 존재 → add_source 호출 안 됨."""
        from datetime import date, timedelta
        yesterday = date.today() - timedelta(days=1)
        old_str = yesterday.strftime("%Y%m%d")
        old_file = tmp_path / f"tst6_{old_str}_120000.log"
        old_file.write_text("old data\n", encoding="utf-8")

        src = self._make_source("TST6", "tst6_")
        watcher = StaticSourceWatcher([src], [tmp_path])
        tailer = MultiTailer()

        watcher.refresh(tailer)
        assert "TST6" not in tailer._sources

    def test_static_watcher_E_missing_dir_no_crash(self, tmp_path: Path):
        """E: dirs에 미존재 디렉토리 포함 → 예외 없이 스킵."""
        nonexistent = tmp_path / "no_such_dir"
        src = self._make_source("TST7", "tst7_")
        watcher = StaticSourceWatcher([src], [nonexistent])
        tailer = MultiTailer()
        # 예외 발생 없어야 함
        watcher.refresh(tailer)
        assert "TST7" not in tailer._sources

    def test_static_watcher_E_find_latest_log_returns_none(self, tmp_path: Path):
        """E: 패턴 매칭 파일 0개 → 해당 source는 등록되지 않음, 예외 없음."""
        src = self._make_source("TST8", "no_match_pattern_xyz_")
        watcher = StaticSourceWatcher([src], [tmp_path])
        tailer = MultiTailer()

        watcher.refresh(tailer)
        assert "TST8" not in tailer._sources

    def test_static_watcher_public_safe_C_does_not_register_api_log(self, tmp_path: Path):
        """C: public-safe source list를 받은 watcher는 api_*.log를 등록하지 않는다."""
        from datetime import date

        today_str = date.today().strftime("%Y%m%d")
        (tmp_path / f"api_{today_str}_120000.log").write_text(
            "pid=1234 role=watchdog [process-watch]\n",
            encoding="utf-8",
        )
        (tmp_path / f"frontend_2_{today_str}_120000.log").write_text(
            "ERROR public-safe frontend line\n",
            encoding="utf-8",
        )

        watcher = StaticSourceWatcher(get_sources(public_safe=True), [tmp_path])
        tailer = MultiTailer()

        watcher.refresh(tailer)

        assert "FRONTEND" in tailer._sources
        assert "API" not in tailer._sources
        assert not any(name.startswith(("PR:", "PS:")) for name in tailer._sources)
