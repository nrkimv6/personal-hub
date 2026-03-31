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
    ps1_path = Path(__file__).resolve().parent.parent.parent / "scripts" / "logs.ps1"
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
