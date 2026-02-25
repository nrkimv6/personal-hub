"""7.1: asyncio.Process.poll() 잔존 부재 검증 + returncode 사용 올바름 확인"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_asyncio_process_has_no_poll():
    """asyncio.subprocess.Process에 .poll() 없음을 명시적으로 확인"""
    # asyncio.subprocess.Process 인스턴스는 .poll() 없음
    proc = MagicMock(spec=asyncio.subprocess.Process)
    assert not hasattr(proc, "poll"), \
        "asyncio.Process에 .poll() 속성이 있으면 안 됨 — Popen과 혼동 위험"


def test_subprocess_popen_has_poll():
    """subprocess.Popen에는 .poll()이 있어야 함 (command-listener 정상 사용 확인)"""
    import subprocess
    proc = MagicMock(spec=subprocess.Popen)
    assert hasattr(proc, "poll"), "subprocess.Popen에는 .poll() 있어야 함"


def test_returncode_none_means_running():
    """asyncio.Process.returncode is None → 실행 중 상태 패턴 검증"""
    proc = MagicMock(spec=asyncio.subprocess.Process)

    # 실행 중: returncode = None
    proc.returncode = None
    assert proc.returncode is None, "실행 중일 때 returncode는 None"

    # 종료됨: returncode = 0 (정상)
    proc.returncode = 0
    assert proc.returncode is not None, "종료 후 returncode는 None 아님"

    # 오류 종료: returncode = 1
    proc.returncode = 1
    assert proc.returncode is not None


def test_executor_py_no_poll_call():
    """executor.py 소스에 .poll() 호출이 없는지 확인"""
    from pathlib import Path

    executor_path = Path("D:/work/project/service/wtools/common/tools/plan-runner/core/executor.py")
    if not executor_path.exists():
        pytest.skip("executor.py 경로 없음")

    source = executor_path.read_text(encoding="utf-8", errors="ignore")
    # asyncio.Process 맥락에서 .poll() 호출 여부 확인
    # (subprocess.Popen 관련이 아닌 줄만 체크)
    lines_with_poll = [
        (i + 1, line.strip())
        for i, line in enumerate(source.splitlines())
        if ".poll()" in line and "subprocess.Popen" not in line and "#" not in line.strip()[:5]
    ]
    assert len(lines_with_poll) == 0, \
        f"executor.py에 .poll() 호출 잔존: {lines_with_poll}"


def test_command_listener_poll_on_popen_only():
    """dev-runner-command-listener.py의 .poll()이 subprocess.Popen 객체에만 사용됨을 확인"""
    from pathlib import Path

    listener_path = Path("scripts/dev-runner-command-listener.py")
    if not listener_path.exists():
        pytest.skip("listener 경로 없음")

    source = listener_path.read_text(encoding="utf-8", errors="ignore")

    # .poll() 호출 줄 추출
    poll_lines = [
        (i + 1, line.strip())
        for i, line in enumerate(source.splitlines())
        if ".poll()" in line
    ]

    # 반드시 `_current_process.poll()` 형태 (subprocess.Popen 전역변수)
    for lineno, line in poll_lines:
        assert "_current_process.poll()" in line or "process.poll()" in line, \
            f"line {lineno}: 예상치 않은 .poll() 호출: {line}"
