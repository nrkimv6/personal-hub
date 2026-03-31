"""
cli.py — CLI 진입점 (static 모드 출력)

사용법:
    python -m app.log_viewer [target] [--admin] [--lines N]

target:
    생략 시 — 모든 소스 표시 (admin 여부에 따라 필터)
    "api", "worker" 등 — 해당 소스 이름(대소문자 무시)만 표시
    "plan-runner" — 활성 plan-runner 목록 표시

옵션:
    --admin    admin 전용 소스 포함
    --lines N  tail 줄수 오버라이드 (기본: 소스별 tail_lines)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from rich.console import Console
    from rich.rule import Rule
    from rich.text import Text

    _RICH = True
except ImportError:  # pragma: no cover
    _RICH = False

from app.log_viewer.config import (
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
from app.log_viewer.stale import is_stale

# ---------------------------------------------------------------------------
# 기본 로그 디렉토리 (프로젝트 루트 기준)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_LOGS_DIR = _PROJECT_ROOT / "logs"
_LOGS_ADMIN_DIR = _PROJECT_ROOT / "logs" / "admin"

console: "Console | None" = Console() if _RICH else None


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


def _tail_file(file_path: Path, n: int) -> list[str]:
    """파일 마지막 n줄을 반환한다."""
    try:
        with file_path.open("r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return [ln.rstrip("\n") for ln in lines[-n:]] if lines else []
    except OSError:
        return []


# ---------------------------------------------------------------------------
# 소스 출력
# ---------------------------------------------------------------------------

def _resolve_dirs(admin: bool) -> list[Path]:
    """admin 여부에 따라 탐색 디렉토리 목록을 반환한다."""
    dirs = [_LOGS_DIR]
    if admin:
        dirs.append(_LOGS_ADMIN_DIR)
    return dirs


def _print_source(source_name: str, files: list[Path], color: str, lines: int) -> None:
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
        tail_lines = _tail_file(f, lines)
        if tail_lines:
            for ln in tail_lines:
                _print_line(ln)
        else:
            _print_line("  (비어있음)")


def show_source(name: str, admin: bool, lines_override: int | None) -> None:
    """단일 소스를 찾아 출력한다."""
    src = get_source_by_name(name.upper())
    if src is None:
        print(f"알 수 없는 소스: {name!r}", file=sys.stderr)
        return

    dirs = _resolve_dirs(admin)
    # glob 패턴으로 탐색 (finder는 prefix 기준이므로 * 추가)
    patterns = [f"{p}*" for p in src.patterns]
    files = find_latest_logs(patterns, dirs, max_count=3)
    n = lines_override if lines_override is not None else src.tail_lines
    _print_source(src.name, files, src.color, n)


def show_all_sources(admin: bool, lines_override: int | None) -> None:
    """admin 여부에 따른 모든 소스를 출력한다."""
    sources = get_sources(admin)
    dirs = _resolve_dirs(admin)
    for src in sources:
        patterns = [f"{p}*" for p in src.patterns]
        files = find_latest_logs(patterns, dirs, max_count=3)
        n = lines_override if lines_override is not None else src.tail_lines
        _print_source(src.name, files, src.color, n)


# ---------------------------------------------------------------------------
# plan-runner 출력
# ---------------------------------------------------------------------------

def show_plan_runners(admin: bool, lines_override: int | None) -> None:
    """활성 plan-runner 목록을 표시한다. Redis 미연결 시 정적 fallback."""
    runners = get_active_runners()

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
        _print_source("PLAN-RUNNER (fallback)", log_files, PLAN_RUNNER_COLOR, n_log)
        _print_source("PLAN-RUNNER-STREAM (fallback)", stream_files, PLAN_RUNNER_STREAM_COLOR, n_stream)
        return

    # Redis에서 가져온 활성 runner 표시
    for runner in runners:
        _show_runner(runner, lines_override)


def _show_runner(runner: RunnerInfo, lines_override: int | None) -> None:
    label = f"PLAN-RUNNER [{runner.display_name}]  pid={runner.pid or '?'}"
    n_log = lines_override if lines_override is not None else PLAN_RUNNER_TAIL
    n_stream = lines_override if lines_override is not None else PLAN_RUNNER_STREAM_TAIL

    # 메인 로그
    if runner.log_path:
        log_file = Path(runner.log_path)
        if log_file.exists():
            _print_rule(f"{label}  {log_file.name}", PLAN_RUNNER_COLOR)
            for ln in _tail_file(log_file, n_log):
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
            for ln in _tail_file(stream_file, n_stream):
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
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    target: str | None = args.target
    admin: bool = args.admin
    lines: int | None = args.lines

    if target is None:
        show_all_sources(admin, lines)
        show_plan_runners(admin, lines)
    elif target.lower() == "plan-runner":
        show_plan_runners(admin, lines)
    else:
        show_source(target, admin, lines)


if __name__ == "__main__":
    main()
