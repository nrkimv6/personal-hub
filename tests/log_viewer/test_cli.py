"""
tests/log_viewer/test_cli.py — cli.py 단위/통합 테스트 (Phase 3)

_tail_file(), build_parser(), show_source() 등의 신규 기능을 검증한다.
"""
from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.log_viewer.cli import (
    _print_follow_line,
    _tail_file,
    build_parser,
    main,
    show_source,
)
from app.log_viewer.config import CLEANUP_FILTER_PATTERN
from app.log_viewer.follower import LogLine


# ---------------------------------------------------------------------------
# _tail_file — filter_pattern (Phase 3)
# ---------------------------------------------------------------------------

class TestTailFileFilter:
    def test_no_filter_returns_all_lines(self, tmp_path: Path):
        """R(Right): filter_pattern=None → 모든 라인 반환 (기존 동작 유지)"""
        f = tmp_path / "test.log"
        f.write_text("line1\nline2\nline3\n", encoding="utf-8")
        result = _tail_file(f, 10)
        assert result == ["line1", "line2", "line3"]

    def test_filter_keeps_matching_lines(self, tmp_path: Path):
        """R(Right): cleanup 패턴 포함 라인만 반환"""
        f = tmp_path / "test.log"
        content = (
            "normal log line\n"
            "[cleanup] stale runner removed\n"
            "another normal line\n"
            "force_cleanup called\n"
        )
        f.write_text(content, encoding="utf-8")
        result = _tail_file(f, 10, filter_pattern=CLEANUP_FILTER_PATTERN)
        assert len(result) == 2
        assert "[cleanup] stale runner removed" in result
        assert "force_cleanup called" in result

    def test_filter_no_match_returns_empty(self, tmp_path: Path):
        """B(Boundary): 매칭 라인 0개 → 빈 리스트"""
        f = tmp_path / "test.log"
        f.write_text("no match here\nanother normal line\n", encoding="utf-8")
        result = _tail_file(f, 10, filter_pattern=CLEANUP_FILTER_PATTERN)
        assert result == []

    def test_filter_respects_n_limit(self, tmp_path: Path):
        """B(Boundary): 매칭 라인이 n보다 많으면 마지막 n줄만 반환"""
        lines = [f"[cleanup] event {i}" for i in range(10)]
        f = tmp_path / "test.log"
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = _tail_file(f, 3, filter_pattern=CLEANUP_FILTER_PATTERN)
        assert len(result) == 3
        assert result[-1] == "[cleanup] event 9"


# ---------------------------------------------------------------------------
# build_parser — --cleanup 인자 (Phase 3)
# ---------------------------------------------------------------------------

class TestBuildParser:
    def test_cleanup_flag_default_false(self):
        """R(Right): --cleanup 미전달 → cleanup=False"""
        parser = build_parser()
        args = parser.parse_args([])
        assert args.cleanup is False

    def test_cleanup_flag_true(self):
        """R(Right): --cleanup 전달 → cleanup=True"""
        parser = build_parser()
        args = parser.parse_args(["--cleanup"])
        assert args.cleanup is True

    def test_cleanup_with_target(self):
        """R(Right): target + --cleanup 조합"""
        parser = build_parser()
        args = parser.parse_args(["api", "--cleanup"])
        assert args.target == "api"
        assert args.cleanup is True


# ---------------------------------------------------------------------------
# Phase T3 통합 TC
# ---------------------------------------------------------------------------

class TestShowSourceWithCleanup:
    def test_show_source_with_cleanup_filter(self, tmp_path: Path, monkeypatch):
        """
        T3: tmp_path에 cleanup/일반 라인 혼합 로그 생성 →
        show_source(..., cleanup=True) → cleanup 패턴 라인만 출력
        """
        # 로그 파일 생성 (DEV-RUNNER 소스 패턴에 맞는 파일명)
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        # DEV-RUNNER 소스 패턴: dev_runner_command_listener*
        log_file = log_dir / "dev_runner_command_listener-20260305.log"
        log_file.write_text(
            "normal startup line\n"
            "[cleanup] removed stale runner abc\n"
            "another info line\n"
            "force_cleanup called by scheduler\n",
            encoding="utf-8",
        )

        # _LOGS_DIR, _LOGS_ADMIN_DIR를 tmp_path 기준으로 패치
        monkeypatch.setattr("app.log_viewer.cli._LOGS_DIR", log_dir)
        monkeypatch.setattr("app.log_viewer.cli._LOGS_ADMIN_DIR", log_dir / "admin")

        captured = StringIO()
        with patch("app.log_viewer.cli._print_line", side_effect=lambda t: captured.write(t + "\n")):
            show_source("DEV-RUNNER", admin=False, lines_override=50, cleanup=True)

        output = captured.getvalue()
        assert "[cleanup] removed stale runner abc" in output
        assert "force_cleanup called by scheduler" in output
        assert "normal startup line" not in output
        assert "another info line" not in output


class TestMainCleanupArgv:
    def test_main_devrunner_cleanup_argv(self, tmp_path: Path, monkeypatch):
        """
        T3: main(["dev-runner", "--admin", "--cleanup"]) 실행 →
        정상 종료 + cleanup 필터 적용
        """
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        # DEV-RUNNER 소스 패턴: dev_runner_command_listener*
        log_file = log_dir / "dev_runner_command_listener-20260305.log"
        log_file.write_text(
            "normal line\n[cleanup] event\n",
            encoding="utf-8",
        )

        monkeypatch.setattr("app.log_viewer.cli._LOGS_DIR", log_dir)
        monkeypatch.setattr("app.log_viewer.cli._LOGS_ADMIN_DIR", log_dir)

        captured = StringIO()
        with patch("app.log_viewer.cli._print_line", side_effect=lambda t: captured.write(t + "\n")):
            # 예외 없이 정상 종료되어야 함
            main(["dev-runner", "--admin", "--cleanup"])

        output = captured.getvalue()
        assert "[cleanup] event" in output
        assert "normal line" not in output

    def test_main_devrunner_alias_static_right(self, tmp_path: Path, monkeypatch):
        """R: main(["devrunner"])도 DEV-RUNNER 소스로 정규화된다."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "dev_runner_command_listener-20260504.log").write_text(
            "[cleanup] alias event\nnormal line\n",
            encoding="utf-8",
        )

        monkeypatch.setattr("app.log_viewer.cli._LOGS_DIR", log_dir)
        monkeypatch.setattr("app.log_viewer.cli._LOGS_ADMIN_DIR", log_dir)

        captured = StringIO()
        err = StringIO()
        with patch("app.log_viewer.cli._print_line", side_effect=lambda t: captured.write(t + "\n")), \
             patch.object(sys, "stderr", err):
            main(["devrunner", "--admin", "--cleanup"])

        output = captured.getvalue()
        assert "[cleanup] alias event" in output
        assert "알 수 없는 소스" not in err.getvalue()

    def test_main_dev_runner_alias_follow_dispatch_right(self):
        """R: follow 모드에서도 dev-runner alias가 단일 DEV-RUNNER source로 dispatch된다."""
        with patch("app.log_viewer.cli.follow_source") as follow_source:
            main(["dev-runner", "--follow", "--admin"])

        follow_source.assert_called_once_with("DEV-RUNNER", True, cleanup=False)

    def test_main_unknown_target_errors_only_for_unregistered_target(self, capsys):
        """B: 진짜 미등록 target만 unknown source 에러를 출력한다."""
        main(["not-a-real-source"])
        captured = capsys.readouterr()
        assert "알 수 없는 소스" in captured.err

    def test_main_devrunner_single_target_does_not_mix_plan_runner_fallback(self):
        """R: devrunner 단일 타겟은 DEV-RUNNER만 조회하고 plan-runner fallback을 섞지 않는다."""
        with patch("app.log_viewer.cli.show_source") as show_source, \
             patch("app.log_viewer.cli.show_plan_runners") as show_plan_runners:
            main(["devrunner", "--admin"])

        show_source.assert_called_once_with("DEV-RUNNER", True, None, cleanup=False)
        show_plan_runners.assert_not_called()

    def test_logs_ps1_validate_set_accepts_dev_runner_alias(self):
        """R: PowerShell wrapper도 dev-runner alias를 ValidateSet에서 차단하지 않는다."""
        script = Path(__file__).resolve().parents[2] / "scripts" / "logs" / "logs.ps1"
        text = script.read_text(encoding="utf-8")

        assert '"devrunner"' in text
        assert '"dev-runner"' in text


class TestWorkerSourceSelection:
    def test_show_source_worker_prefers_structured_worker_log_over_stdout_capture(self, tmp_path: Path, monkeypatch):
        """
        WORKER 소스는 최신 stdout 캡처 파일보다 구조화 본로그(worker_*.log)를 우선해야 한다.
        """
        log_dir = tmp_path / "logs"
        admin_dir = log_dir / "admin"
        admin_dir.mkdir(parents=True)

        worker_log = admin_dir / "worker_20260416_164035.log"
        worker_log.write_text(
            "2026-04-16 23:17:15,234 - [WORKER] INFO - [coupang_monitor] 상태 변경 1건 감지\n",
            encoding="utf-8",
        )

        stdout_log = admin_dir / "stdout_unified_worker_20260416_164033.log"
        stdout_log.write_text(
            "2026-04-16 23:17:15,227 - [API] INFO - Notification message sent\n",
            encoding="utf-8",
        )

        worker_log.touch()
        stdout_log.touch()

        monkeypatch.setattr("app.log_viewer.cli._LOGS_DIR", log_dir)
        monkeypatch.setattr("app.log_viewer.cli._LOGS_ADMIN_DIR", admin_dir)

        captured = StringIO()
        with patch("app.log_viewer.cli._print_line", side_effect=lambda t: captured.write(t + "\n")):
            show_source("WORKER", admin=True, lines_override=50)

        output = captured.getvalue()
        assert "상태 변경 1건 감지" in output
        assert "Notification message sent" not in output


class TestRunnerTcFormatEndToEnd:
    def test_runner_tc_format_end_to_end(self):
        """
        T3: Redis mock에 TC runner 등록 →
        get_active_runners() → RunnerInfo.display_name == "t-my-tc", short_id == "t-my-tc"
        """
        from app.log_viewer.runner import get_active_runners
        from unittest.mock import MagicMock

        r = MagicMock()
        r.smembers.return_value = {b"t-my-tc"}

        def _get(key):
            mapping = {
                "plan-runner:runners:t-my-tc:log_file_path": b"D:/logs/plan-runner-t-my-tc-20260305-120000.log",
                "plan-runner:runners:t-my-tc:stream_log_path": None,
                "plan-runner:runners:t-my-tc:plan_file": None,
                "plan-runner:runners:t-my-tc:pid": b"9999",
            }
            return mapping.get(key)

        r.get.side_effect = _get

        result = get_active_runners(r)
        assert len(result) == 1
        info = result[0]
        assert info.display_name == "t-my-tc"
        assert info.short_id == "t-my-tc"


# ---------------------------------------------------------------------------
# Follow 모드 — build_parser / _print_follow_line (Phase T1 items 35-38)
# ---------------------------------------------------------------------------


class TestParserFollowFlag:
    def test_parser_follow_flag(self):
        """R(Right): --follow → args.follow=True, args.cleanup=False."""
        args = build_parser().parse_args(["--follow"])
        assert args.follow is True
        assert args.cleanup is False

    def test_parser_follow_short_flag(self):
        """R(Right): -f → args.follow=True."""
        args = build_parser().parse_args(["-f"])
        assert args.follow is True

    def test_parser_follow_with_target_and_cleanup(self):
        """R(Right): target + --follow + --cleanup + --admin → 각 필드 정확히 설정."""
        args = build_parser().parse_args(["api", "--follow", "--cleanup", "--admin"])
        assert args.follow is True
        assert args.cleanup is True
        assert args.admin is True
        assert args.target == "api"


class TestPrintFollowLine:
    def test_print_follow_line_format(self, capsys):
        """R(Right): _print_follow_line → 출력에 [SOURCE] + 텍스트 포함."""
        import app.log_viewer.cli as cli_mod

        # rich 비활성화하여 plain print 경로 테스트
        orig_rich = cli_mod._RICH
        try:
            cli_mod._RICH = False
            log_line = LogLine(source="API", text="test message", color="cyan", level="ERROR")
            _print_follow_line(log_line)
        finally:
            cli_mod._RICH = orig_rich

        captured = capsys.readouterr()
        assert "[API]" in captured.out
        assert "test message" in captured.out
