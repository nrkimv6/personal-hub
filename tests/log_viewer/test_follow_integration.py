"""
tests/log_viewer/test_follow_integration.py — Follow 모드 통합 TC (Phase T3)

mock 최소화, 실제 파일시스템 + 스레드 사용.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from app.log_viewer.cli import follow_all_sources, main
from app.log_viewer.config import CLEANUP_FILTER_PATTERN
from app.log_viewer.follower import FileTailer, MultiTailer, _apply_filters


# ---------------------------------------------------------------------------
# T3-42: 단일 소스 실시간 tail (실물 파일 + 스레드)
# ---------------------------------------------------------------------------


def test_follow_single_source_live(tmp_path: Path):
    """T3: 실제 파일에 줄을 스레드로 추가 → FileTailer가 모두 수집함."""
    log_file = tmp_path / "live.log"
    log_file.write_text("", encoding="utf-8")

    tailer = FileTailer(log_file)

    written: list[str] = []

    def writer():
        for i in range(5):
            line = f"line_{i}"
            written.append(line)
            with log_file.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            time.sleep(0.05)

    t = threading.Thread(target=writer, daemon=True)
    t.start()

    collected: list[str] = []
    deadline = time.monotonic() + 3.0  # 최대 3초 대기
    while time.monotonic() < deadline and len(collected) < 5:
        collected.extend(tailer.read_new_lines())
        time.sleep(0.05)

    t.join(timeout=2.0)
    assert len(collected) == 5, f"Expected 5 lines, got {len(collected)}: {collected}"
    assert collected == written


# ---------------------------------------------------------------------------
# T3-43: 다중 소스 MultiTailer 실시간 tail
# ---------------------------------------------------------------------------


def test_follow_multi_tailer_live(tmp_path: Path):
    """T3: 두 파일에 동시에 스레드로 줄 추가 → MultiTailer가 양쪽 수집."""
    file_a = tmp_path / "a.log"
    file_b = tmp_path / "b.log"
    file_a.write_text("", encoding="utf-8")
    file_b.write_text("", encoding="utf-8")

    tailer = MultiTailer()
    tailer.add_source("A", file_a, "cyan")
    tailer.add_source("B", file_b, "green")

    def writer_a():
        for i in range(3):
            with file_a.open("a", encoding="utf-8") as fh:
                fh.write(f"a_line_{i}\n")
            time.sleep(0.05)

    def writer_b():
        for i in range(3):
            with file_b.open("a", encoding="utf-8") as fh:
                fh.write(f"b_line_{i}\n")
            time.sleep(0.05)

    ta = threading.Thread(target=writer_a, daemon=True)
    tb = threading.Thread(target=writer_b, daemon=True)
    ta.start()
    tb.start()

    collected_sources: set[str] = set()
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and len(collected_sources) < 2:
        for ln in tailer.poll_once():
            collected_sources.add(ln.source)
        time.sleep(0.05)

    ta.join(timeout=2.0)
    tb.join(timeout=2.0)

    assert "A" in collected_sources, "Source A not received"
    assert "B" in collected_sources, "Source B not received"


# ---------------------------------------------------------------------------
# T3-44: main() --follow KeyboardInterrupt 처리
# ---------------------------------------------------------------------------


def test_follow_main_argv_keyboard_interrupt():
    """T3: follow_all_sources가 KeyboardInterrupt → main() 예외 없이 정상 종료."""

    def raise_ki(*args, **kwargs):
        raise KeyboardInterrupt

    with patch("app.log_viewer.cli.follow_all_sources", side_effect=raise_ki):
        # sys.exit 미호출, 예외 전파 없음을 검증
        main(["--follow"])  # KeyboardInterrupt가 전파되지 않아야 함


# ---------------------------------------------------------------------------
# T3-45: cleanup 패턴 SSOT 검증
# ---------------------------------------------------------------------------


def test_cleanup_pattern_ssot(tmp_path: Path):
    """T3: config.CLEANUP_FILTER_PATTERN이 follower.py에서 SSOT로 사용됨을 검증."""
    # follower.py의 _apply_filters가 config 패턴을 그대로 사용하는지 확인
    assert _apply_filters("[cleanup] runner removed", error_only=False, cleanup_pattern=CLEANUP_FILTER_PATTERN)
    assert _apply_filters("force_cleanup called", error_only=False, cleanup_pattern=CLEANUP_FILTER_PATTERN)
    assert not _apply_filters("normal log line", error_only=False, cleanup_pattern=CLEANUP_FILTER_PATTERN)

    # logs.ps1의 cleanup 하드코딩이 deprecated 함수 내에만 잔존하는지 확인
    # (Follow 블록에서는 하드코딩 제거됨)
    ps1_path = Path(__file__).resolve().parent.parent.parent / "scripts" / "logs" / "logs.ps1"
    ps1_content = ps1_path.read_text(encoding="utf-8")

    # Follow 블록 (if ($Follow)) 내에 cleanup 하드코딩이 없어야 함
    follow_block_start = ps1_content.find("# Real-time follow mode")
    follow_block_end = ps1_content.find("} else {", follow_block_start)
    follow_block = ps1_content[follow_block_start:follow_block_end]

    assert "heartbeat.*cleanup" not in follow_block, (
        "logs.ps1 Follow 블록에 cleanup 패턴 하드코딩이 남아있음"
    )
    assert "force_cleanup|_cleanup_process" not in follow_block, (
        "logs.ps1 Follow 블록에 cleanup 패턴 하드코딩이 남아있음"
    )


# ---------------------------------------------------------------------------
# T3-46: 부팅 직후 파일 미존재 → StaticSourceWatcher 자동 감지 (근본 원인 재현)
# ---------------------------------------------------------------------------


def test_follow_all_sources_picks_up_late_created_file(tmp_path: Path, monkeypatch):
    """T3: 빈 logs/ 시작 → StaticSourceWatcher refresh 후 새 파일 감지 + tailer 등록.

    근본 원인 재현:
      - 수정 전: follow_all_sources 시작 시 파일 없으면 영구 누락
      - 수정 후: StaticSourceWatcher가 이후 생성된 파일을 감지하여 자동 등록
    """
    from datetime import date

    from app.log_viewer import cli as cli_mod
    from app.log_viewer import follower as follower_mod
    from app.log_viewer.config import get_sources
    from app.log_viewer.finder import find_latest_log
    from app.log_viewer.follower import MultiTailer, StaticSourceWatcher
    from app.log_viewer.stale import is_stale

    # MONITOR_LOG_DIR로 빈 tmp_path 주입
    monkeypatch.setenv("MONITOR_LOG_DIR", str(tmp_path))
    (tmp_path / "admin").mkdir()
    monkeypatch.setattr(follower_mod.StaticSourceWatcher, "_REFRESH_INTERVAL", 0.0)

    dirs = cli_mod._resolve_dirs(admin=True)
    sources = list(get_sources(admin=True))
    tailer = MultiTailer()

    # 초기 스캔 (follow_all_sources 시작과 동일) — 파일 없음, 아무것도 등록 안 됨
    for src in sources:
        patterns = [f"{p}*" for p in src.patterns]
        path = find_latest_log(patterns, dirs)
        if path is not None and not is_stale(path):
            tailer.add_source(src.name, path, src.color)

    assert len(tailer._sources) == 0, f"초기 등록 없어야 함, got: {list(tailer._sources)}"

    watcher = StaticSourceWatcher(sources, dirs)

    # 아직 파일 없음 → watcher도 등록 안 됨
    watcher.refresh(tailer)
    assert "MERGE-ORCH" not in tailer._sources

    # 부팅 후 파일 생성 시뮬레이션
    today_str = date.today().strftime("%Y%m%d")
    log_file = tmp_path / f"merge-orchestrator_{today_str}_120000.log"
    log_file.write_text("startup_merged\n", encoding="utf-8")

    # StaticSourceWatcher 재스캔 (throttle=0으로 설정됨)
    watcher._last_refresh = -float("inf")
    watcher.refresh(tailer)

    assert "MERGE-ORCH" in tailer._sources, (
        "StaticSourceWatcher가 늦게 생성된 파일을 감지하지 못했음 (수정 전 버그 재발)"
    )

    # initial_tail로 이미 기록된 줄도 반환
    lines = tailer.poll_once()
    assert any(ln.text == "startup_merged" for ln in lines), (
        f"initial_tail 줄 반환 안 됨. lines={[ln.text for ln in lines]}"
    )


# ---------------------------------------------------------------------------
# T3-47: 어제 파일 점착 → stale 필터로 차단, 오늘 파일로 교체 (모순점 1 재현)
# ---------------------------------------------------------------------------


def test_follow_all_sources_skips_stale_yesterday_file(tmp_path: Path, monkeypatch):
    """T3: 어제 파일만 존재 시 stale 필터로 등록 차단 → 오늘 파일 생성 후 watcher가 교체.

    모순점 1 재현:
      - 수정 전: find_latest_log가 어제 파일을 반환 → 영원히 어제 파일을 tail
      - 수정 후: is_stale로 차단 → StaticSourceWatcher가 오늘 파일 생성 시 교체 등록
    """
    from datetime import date, timedelta

    from app.log_viewer import cli as cli_mod
    from app.log_viewer import follower as follower_mod
    from app.log_viewer.config import get_sources
    from app.log_viewer.finder import find_latest_log
    from app.log_viewer.follower import MultiTailer, StaticSourceWatcher
    from app.log_viewer.stale import is_stale

    monkeypatch.setenv("MONITOR_LOG_DIR", str(tmp_path))
    (tmp_path / "admin").mkdir()
    monkeypatch.setattr(follower_mod.StaticSourceWatcher, "_REFRESH_INTERVAL", 0.0)

    today = date.today()
    yesterday = today - timedelta(days=1)
    today_str = today.strftime("%Y%m%d")
    yesterday_str = yesterday.strftime("%Y%m%d")

    # 어제 파일만 존재
    old_file = tmp_path / f"merge-orchestrator_{yesterday_str}_180000.log"
    old_file.write_text("old_line\n", encoding="utf-8")

    dirs = cli_mod._resolve_dirs(admin=True)
    sources = list(get_sources(admin=True))
    tailer = MultiTailer()

    # 초기 스캔: 어제 파일 발견 → is_stale로 차단 (수정 후 동작)
    merge_src = next((s for s in sources if s.name == "MERGE-ORCH"), None)
    assert merge_src is not None, "MERGE-ORCH 소스가 config에 없음"
    patterns = [f"{p}*" for p in merge_src.patterns]
    path = find_latest_log(patterns, dirs)
    assert path is not None, "어제 파일이 find_latest_log에서 발견되지 않음"
    assert is_stale(path), f"어제 파일이 stale로 판정되지 않음: {path.name}"
    # stale이므로 등록 안 함 (follow_all_sources의 수정된 로직)
    # tailer에 add_source 호출 안 함 → MERGE-ORCH 없어야 함
    assert "MERGE-ORCH" not in tailer._sources

    # watcher도 stale로 차단
    watcher = StaticSourceWatcher(sources, dirs)
    watcher.refresh(tailer)
    assert "MERGE-ORCH" not in tailer._sources, "어제 파일이 stale임에도 등록됨"

    # 오늘 파일 생성
    new_file = tmp_path / f"merge-orchestrator_{today_str}_090000.log"
    new_file.write_text("today_line\n", encoding="utf-8")

    # watcher 재스캔 → 오늘 파일 발견 + 등록
    watcher._last_refresh = -float("inf")
    watcher.refresh(tailer)

    assert "MERGE-ORCH" in tailer._sources, (
        "StaticSourceWatcher가 오늘 파일을 감지하지 못했음 (어제 파일 점착 미해결)"
    )

    # 오늘 파일의 라인이 initial_tail로 반환돼야 함
    lines = tailer.poll_once()
    assert any(ln.text == "today_line" for ln in lines), (
        f"오늘 파일 initial_tail 줄 반환 안 됨. lines={[ln.text for ln in lines]}"
    )
