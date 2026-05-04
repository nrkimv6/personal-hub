"""
cli.py — CLI 진입점 (static 모드 + follow 모드 출력)

사용법:
    python -m app.log_viewer [target] [--admin] [--lines N] [--follow] [--cleanup]

target:
    생략 시 — 모든 소스 표시 (admin 여부에 따라 필터)
    "api", "worker" 등 — 해당 소스 이름(대소문자 무시)만 표시
    "plan-runner" — 활성 plan-runner 목록 표시

옵션:
    --admin      admin 전용 소스 포함
    --lines N    tail 줄수 오버라이드 (기본: 소스별 tail_lines)
    --follow/-f  실시간 tail 모드 (Follow 모드)
    --cleanup    cleanup/정리 이벤트 라인만 표시
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

try:
    from rich.console import Console
    from rich.rule import Rule
    from rich.text import Text

    _RICH = True
except ImportError:  # pragma: no cover
    _RICH = False

from app.log_viewer.config import (
    CLEANUP_FILTER_PATTERN,
    LOG_SOURCES,
    PLAN_RUNNER_COLOR,
    PLAN_RUNNER_LOG_PATTERN,
    PLAN_RUNNER_STREAM_COLOR,
    PLAN_RUNNER_STREAM_PATTERN,
    PLAN_RUNNER_STREAM_TAIL,
    PLAN_RUNNER_TAIL,
    get_source_by_name,
    get_sources,
)
from app.log_viewer.finder import find_latest_log, find_latest_logs
from app.log_viewer.runner import RunnerInfo, get_active_runners
from app.log_viewer.follower import LogLine, MultiTailer, RunnerWatcher, StaticSourceWatcher
from app.log_viewer.stale import is_stale

# ---------------------------------------------------------------------------
# 기본 로그 디렉토리 (프로젝트 루트 기준)
# ---------------------------------------------------------------------------
import os as _os

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_LOGS_DIR = _PROJECT_ROOT / "logs"
_LOGS_ADMIN_DIR = _PROJECT_ROOT / "logs" / "admin"


def _resolve_logs_root() -> Path:
    """MONITOR_LOG_DIR 환경변수가 설정되어 있으면 그 경로를 사용한다.

    환경변수 미설정 시 _LOGS_DIR을 사용 (기존 monkeypatch 호환).
    """
    override = _os.environ.get("MONITOR_LOG_DIR")
    return Path(override) if override else _LOGS_DIR

console: "Console | None" = Console() if _RICH else None

_TARGET_ALIASES = {
    "DEVRUNNER": "DEV-RUNNER",
    "DEV_RUNNER": "DEV-RUNNER",
    "DEV-RUNNER": "DEV-RUNNER",
}


def _normalize_target(target: str) -> str:
    key = target.strip().upper()
    return _TARGET_ALIASES.get(key, key)


# ---------------------------------------------------------------------------
# 출력 헬퍼
# ---------------------------------------------------------------------------

def _print_rule(title: str, color: str = "white") -> None:
    if _RICH and console:
        console.print(Rule(f"[bold {color}]{title}[/]", style=color))
    else:
        print(f"\n{'='*60} {title} {'='*60}")


def _print_colored(text: str, color: str) -> None:
    if _RICH and console:
        console.print(Text(text, style=color), end="")
    else:
        print(text, end="")


def _print_line(text: str) -> None:
    if _RICH and console:
        console.print(text, highlight=False, markup=False)
    else:
        print(text)


def _tail_file(file_path: Path, n: int, filter_pattern: str | None = None) -> list[str]:
    """파일 마지막 n줄을 반환한다. filter_pattern이 있으면 매칭 라인만 유지 후 마지막 n줄 반환."""
    try:
        with file_path.open("r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        stripped = [ln.rstrip("\n") for ln in lines] if lines else []
        if filter_pattern is not None:
            stripped = [ln for ln in stripped if re.search(filter_pattern, ln)]
        return stripped[-n:] if stripped else []
    except OSError:
        return []


# ---------------------------------------------------------------------------
# Follow 모드 출력 헬퍼
# ---------------------------------------------------------------------------

_LEVEL_COLORS: dict[str, str] = {
    "ERROR": "red bold",
    "CRITICAL": "red bold",
    "WARNING": "yellow",
    "WARN": "yellow",
    "INFO": "green",
    "DEBUG": "bright_black",
}


def _print_follow_line(log_line: LogLine) -> None:
    """Follow 모드에서 단일 LogLine을 출력한다."""
    prefix = f"[{log_line.source}] "
    if _RICH and console:
        t = Text()
        t.append(prefix, style=log_line.color)
        level_color = _LEVEL_COLORS.get(log_line.level or "", "")
        if level_color:
            t.append(log_line.text, style=level_color)
        else:
            t.append(log_line.text)
        console.print(t, highlight=False, markup=False)
    else:
        print(f"{prefix}{log_line.text}")


def _print_follow_banner(target: str, cleanup: bool) -> None:
    """Follow 시작 배너를 출력한다."""
    _print_rule(f"Following {target}", "cyan")
    if cleanup:
        _print_colored("  cleanup 필터 활성\n", "yellow")
    _print_colored("  Ctrl+C to stop\n", "bright_black")


# ---------------------------------------------------------------------------
# 소스 출력
# ---------------------------------------------------------------------------

def _resolve_dirs(admin: bool) -> list[Path]:
    """admin 여부에 따라 탐색 디렉토리 목록을 반환한다.

    MONITOR_LOG_DIR 환경변수가 설정된 경우 해당 경로를 기준으로 사용한다. (테스트용)
    """
    logs_root = _resolve_logs_root()
    dirs = [logs_root]
    if admin:
        dirs.append(logs_root / "admin")
    return dirs


def _print_source(source_name: str, files: list[Path], color: str, lines: int, filter_pattern: str | None = None) -> None:
    """로그 소스 헤더와 tail 내용을 출력한다."""
    if not files:
        _print_rule(f"{source_name}  [파일 없음]", color)
        return

    for i, f in enumerate(files):
        label = source_name if i == 0 else f"  ↳ (이전)"
        stale_mark = ""
        # stale 표시는 파일이 여럿일 때 이전 파일에만
        if i < len(files) - 1:
            if is_stale(f, reference_path=files[-1]):
                stale_mark = " [stale]"

        _print_rule(f"{label}  {f.name}{stale_mark}", color)
        tail_lines = _tail_file(f, lines, filter_pattern=filter_pattern)
        if tail_lines:
            for ln in tail_lines:
                _print_line(ln)
        else:
            _print_line("  (비어있음)")


def show_source(name: str, admin: bool, lines_override: int | None, cleanup: bool = False) -> None:
    """단일 소스를 찾아 출력한다."""
    src = get_source_by_name(_normalize_target(name))
    if src is None:
        print(f"알 수 없는 소스: {name!r}", file=sys.stderr)
        return

    dirs = _resolve_dirs(admin)
    # glob 패턴으로 탐색 (finder는 prefix 기준이므로 * 추가)
    patterns = [f"{p}*" for p in src.patterns]
    files = find_latest_logs(patterns, dirs, max_count=3)
    n = lines_override if lines_override is not None else src.tail_lines
    _print_source(src.name, files, src.color, n, filter_pattern=CLEANUP_FILTER_PATTERN if cleanup else None)


def show_all_sources(admin: bool, lines_override: int | None, cleanup: bool = False) -> None:
    """admin 여부에 따른 모든 소스를 출력한다."""
    sources = get_sources(admin)
    dirs = _resolve_dirs(admin)
    for src in sources:
        patterns = [f"{p}*" for p in src.patterns]
        files = find_latest_logs(patterns, dirs, max_count=3)
        n = lines_override if lines_override is not None else src.tail_lines
        _print_source(src.name, files, src.color, n, filter_pattern=CLEANUP_FILTER_PATTERN if cleanup else None)


# ---------------------------------------------------------------------------
# Follow 모드 — 소스 tail
# ---------------------------------------------------------------------------


def follow_source(name: str, admin: bool, cleanup: bool = False) -> None:
    """단일 소스를 실시간 tail한다."""
    src = get_source_by_name(_normalize_target(name))
    if src is None:
        print(f"알 수 없는 소스: {name!r}", file=sys.stderr)
        return

    dirs = _resolve_dirs(admin)
    patterns = [f"{p}*" for p in src.patterns]
    path = find_latest_log(patterns, dirs)
    if path is None:
        print(f"[{src.name}] 로그 파일 없음", file=sys.stderr)
        return

    tailer = MultiTailer(cleanup=cleanup)
    tailer.add_source(src.name, path, src.color, error_only=src.error_only)

    _print_follow_banner(src.name, cleanup)
    try:
        while True:
            for ln in tailer.poll_once():
                _print_follow_line(ln)
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass


def follow_all_sources(admin: bool, cleanup: bool = False) -> None:
    """모든 소스를 실시간 통합 tail한다.

    - plan-runner는 RunnerWatcher로 동적 관리.
    - 정적 소스는 StaticSourceWatcher가 10초 주기로 재스캔 → 부팅 직후 누락 소스 자동 감지.
    - 시작 시 stale 필터 적용 → 어제 파일에 점착되지 않음.
    """
    tailer = MultiTailer(cleanup=cleanup)
    dirs = _resolve_dirs(admin)
    sources = list(get_sources(admin))

    # 시작 시 1회 스캔: stale 파일은 제외 (StaticSourceWatcher가 오늘 파일 생기면 추가)
    for src in sources:
        patterns = [f"{p}*" for p in src.patterns]
        path = find_latest_log(patterns, dirs)
        if path is not None and not is_stale(path):
            tailer.add_source(src.name, path, src.color, error_only=src.error_only)
        elif path is not None and is_stale(path):
            print(f"[{src.name}] (오늘 로그 파일 대기 중...)", flush=True)

    runner_watcher = RunnerWatcher()
    static_watcher = StaticSourceWatcher(sources, dirs)

    _print_follow_banner("ALL", cleanup)
    try:
        while True:
            static_watcher.refresh(tailer)
            runner_watcher.refresh(tailer)
            for ln in tailer.poll_once():
                _print_follow_line(ln)
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------------------------
# plan-runner 출력
# ---------------------------------------------------------------------------

def show_plan_runners(admin: bool, lines_override: int | None, cleanup: bool = False) -> None:
    """활성 plan-runner 목록을 표시한다. Redis 미연결 시 정적 fallback."""
    runners = get_active_runners()
    fp = CLEANUP_FILTER_PATTERN if cleanup else None

    if not runners:
        # Fallback: 정적 파일 탐색
        dirs = _resolve_dirs(admin)
        log_files = find_latest_logs([PLAN_RUNNER_LOG_PATTERN], dirs, max_count=3)
        stream_files = find_latest_logs([PLAN_RUNNER_STREAM_PATTERN], dirs, max_count=3)

        if not log_files and not stream_files:
            _print_rule("PLAN-RUNNER  [활성 runner 없음]", PLAN_RUNNER_COLOR)
            return

        n_log = lines_override if lines_override is not None else PLAN_RUNNER_TAIL
        n_stream = lines_override if lines_override is not None else PLAN_RUNNER_STREAM_TAIL
        _print_source("PLAN-RUNNER (fallback)", log_files, PLAN_RUNNER_COLOR, n_log, filter_pattern=fp)
        _print_source("PLAN-RUNNER-STREAM (fallback)", stream_files, PLAN_RUNNER_STREAM_COLOR, n_stream, filter_pattern=fp)
        return

    # Redis에서 가져온 활성 runner 표시
    for runner in runners:
        _show_runner(runner, lines_override, filter_pattern=fp)


def _show_runner(runner: RunnerInfo, lines_override: int | None, filter_pattern: str | None = None) -> None:
    label = f"PLAN-RUNNER [{runner.display_name}]  pid={runner.pid or '?'}"
    n_log = lines_override if lines_override is not None else PLAN_RUNNER_TAIL
    n_stream = lines_override if lines_override is not None else PLAN_RUNNER_STREAM_TAIL

    # 메인 로그
    if runner.log_path:
        log_file = Path(runner.log_path)
        if log_file.exists():
            _print_rule(f"{label}  {log_file.name}", PLAN_RUNNER_COLOR)
            for ln in _tail_file(log_file, n_log, filter_pattern=filter_pattern):
                _print_line(ln)
        else:
            _print_rule(f"{label}  [파일 없음]", PLAN_RUNNER_COLOR)
    else:
        _print_rule(f"{label}  [log_path 없음]", PLAN_RUNNER_COLOR)

    # 스트림 로그
    if runner.stream_path:
        stream_file = Path(runner.stream_path)
        if stream_file.exists():
            _print_rule(f"  ↳ STREAM  {stream_file.name}", PLAN_RUNNER_STREAM_COLOR)
            for ln in _tail_file(stream_file, n_stream, filter_pattern=filter_pattern):
                _print_line(ln)


# ---------------------------------------------------------------------------
# argparse + main
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.log_viewer",
        description="Monitor Page 로그 뷰어 (static 모드)",
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help=(
            "표시할 로그 소스 이름 (예: api, worker, plan-runner). "
            "생략 시 모든 소스 표시."
        ),
    )
    parser.add_argument(
        "--admin",
        action="store_true",
        default=False,
        help="Admin 전용 소스 포함",
    )
    parser.add_argument(
        "--lines",
        "-n",
        type=int,
        default=None,
        metavar="N",
        help="출력할 tail 줄수 (기본: 소스별 설정값)",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        default=False,
        help="cleanup/정리 이벤트 라인만 표시 (모든 타겟에 적용)",
    )
    parser.add_argument(
        "--follow",
        "-f",
        action="store_true",
        default=False,
        help="실시간 tail 모드 (Follow 모드, Ctrl+C로 종료)",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    target: str | None = args.target
    normalized_target = _normalize_target(target) if target is not None else None
    admin: bool = args.admin
    lines: int | None = args.lines
    cleanup: bool = args.cleanup
    follow: bool = args.follow

    if follow:
        # plan-runner는 RunnerWatcher가 follow_all_sources 내부에서 처리
        try:
            if normalized_target is None or normalized_target == "PLAN-RUNNER":
                follow_all_sources(admin, cleanup=cleanup)
            else:
                follow_source(normalized_target, admin, cleanup=cleanup)
        except KeyboardInterrupt:
            pass
        return

    if normalized_target is None:
        show_all_sources(admin, lines, cleanup=cleanup)
        show_plan_runners(admin, lines, cleanup=cleanup)
    elif normalized_target == "PLAN-RUNNER":
        show_plan_runners(admin, lines, cleanup=cleanup)
    else:
        show_source(normalized_target, admin, lines, cleanup=cleanup)


if __name__ == "__main__":
    main()
