"""
test_chat_executor_pid_guard.py — ChatExecutor PID guard TC

Windows PID 재활용으로 인한 self-PID 오인 + unrelated PID 위양성 검출을
_check_stale_pid()와 _is_chat_executor_pid() 수정이 올바르게 차단하는지 검증한다.
"""
import os
import subprocess
import sys
import time
import pytest
from unittest.mock import patch, MagicMock

from app.modules.claude_worker.worker.chat_executor import ChatExecutor, _is_chat_executor_pid
import app.modules.claude_worker.worker.chat_executor as ce


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_pid_file(tmp_path, monkeypatch):
    """독립 PID 파일 경로를 주입하는 fixture."""
    pid_path = tmp_path / "chat_executor_admin.pid"
    monkeypatch.setattr(ce, "PID_FILE", pid_path)
    return pid_path


def _make_executor():
    """DB/redis를 mock으로 대체한 ChatExecutor 인스턴스."""
    executor = ChatExecutor.__new__(ChatExecutor)
    executor.redis_url = "redis://localhost:6379/0"
    executor._stop_event = MagicMock()
    executor._busy = False
    executor.redis_client = MagicMock()
    return executor


# ─────────────────────────────────────────────────────────────
# _check_stale_pid
# ─────────────────────────────────────────────────────────────

def test_check_stale_pid_R_self_pid_excluded(tmp_pid_file):
    """R: PID 파일에 자기 PID → sys.exit 미호출, PID 파일 제거."""
    tmp_pid_file.write_text(str(os.getpid()), encoding="utf-8")
    executor = _make_executor()
    with patch("sys.exit") as mock_exit:
        executor._check_stale_pid()
    mock_exit.assert_not_called()
    assert not tmp_pid_file.exists()


def test_check_stale_pid_R_unrelated_alive_pid_treated_stale(tmp_pid_file):
    """R: 다른 alive PID지만 chat_executor 아닌 경우 → stale 처리 (sys.exit 미호출)."""
    tmp_pid_file.write_text("99999", encoding="utf-8")
    executor = _make_executor()
    with patch("app.modules.claude_worker.worker.chat_executor._is_pid_alive", return_value=True), \
         patch("app.modules.claude_worker.worker.chat_executor._is_chat_executor_pid", return_value=False), \
         patch("sys.exit") as mock_exit:
        executor._check_stale_pid()
    mock_exit.assert_not_called()
    assert not tmp_pid_file.exists()


def test_check_stale_pid_E_dead_pid_cleaned(tmp_pid_file):
    """E: 죽은 PID → 파일 제거 (sys.exit 미호출)."""
    tmp_pid_file.write_text("77777", encoding="utf-8")
    executor = _make_executor()
    with patch("app.modules.claude_worker.worker.chat_executor._is_pid_alive", return_value=False), \
         patch("sys.exit") as mock_exit:
        executor._check_stale_pid()
    mock_exit.assert_not_called()
    assert not tmp_pid_file.exists()


def test_check_stale_pid_R_real_executor_alive_exits(tmp_pid_file):
    """R: alive + chat_executor 토큰 포함 → sys.exit(1) 호출."""
    tmp_pid_file.write_text("55555", encoding="utf-8")
    executor = _make_executor()
    with patch("app.modules.claude_worker.worker.chat_executor._is_pid_alive", return_value=True), \
         patch("app.modules.claude_worker.worker.chat_executor._is_chat_executor_pid", return_value=True), \
         patch("sys.exit") as mock_exit:
        executor._check_stale_pid()
    mock_exit.assert_called_once_with(1)


def test_check_stale_pid_E_corrupt_pid_file_cleaned(tmp_pid_file):
    """E: PID 파일 내용이 숫자가 아닌 경우 → 파일 제거 (sys.exit 미호출)."""
    tmp_pid_file.write_text("not-a-number", encoding="utf-8")
    executor = _make_executor()
    with patch("sys.exit") as mock_exit:
        executor._check_stale_pid()
    mock_exit.assert_not_called()
    assert not tmp_pid_file.exists()


def test_check_stale_pid_R_no_pid_file(tmp_pid_file):
    """R: PID 파일 없을 때 → 아무것도 하지 않음 (sys.exit 미호출)."""
    executor = _make_executor()
    with patch("sys.exit") as mock_exit:
        executor._check_stale_pid()
    mock_exit.assert_not_called()


# ─────────────────────────────────────────────────────────────
# _is_chat_executor_pid
# ─────────────────────────────────────────────────────────────

def test_is_chat_executor_pid_R_match():
    """R: cmdline에 claude_worker.worker.chat_executor 토큰 있으면 True."""
    import psutil
    mock_proc = MagicMock()
    mock_proc.cmdline.return_value = [
        "python", "-m", "app.modules.claude_worker.worker.chat_executor"
    ]
    with patch("psutil.Process", return_value=mock_proc):
        assert _is_chat_executor_pid(12345) is True


def test_is_chat_executor_pid_R_alias_match():
    """R: cmdline에 monitorpage-chat 토큰 있으면 True."""
    import psutil
    mock_proc = MagicMock()
    mock_proc.cmdline.return_value = ["monitorpage-chat.exe"]
    with patch("psutil.Process", return_value=mock_proc):
        assert _is_chat_executor_pid(12346) is True


def test_is_chat_executor_pid_E_no_such_process():
    """E: 존재하지 않는 PID → False (NoSuchProcess 예외)."""
    import psutil
    with patch("psutil.Process", side_effect=psutil.NoSuchProcess(99999)):
        assert _is_chat_executor_pid(99999) is False


def test_is_chat_executor_pid_E_access_denied():
    """E: 접근 거부 → False (AccessDenied 예외)."""
    import psutil
    with patch("psutil.Process", side_effect=psutil.AccessDenied(99998)):
        assert _is_chat_executor_pid(99998) is False


def test_is_chat_executor_pid_R_unrelated_cmdline():
    """R: 무관한 cmdline → False."""
    import psutil
    mock_proc = MagicMock()
    mock_proc.cmdline.return_value = ["python", "some_other_script.py"]
    with patch("psutil.Process", return_value=mock_proc):
        assert _is_chat_executor_pid(11111) is False


# ─────────────────────────────────────────────────────────────
# T3: 실 subprocess 기반 통합 TC
# ─────────────────────────────────────────────────────────────

def test_check_stale_pid_E_real_chat_executor_alive_exits(tmp_pid_file):
    """T3: 실 subprocess에 claude_worker.worker.chat_executor cmdline 토큰 → SystemExit(1)."""
    # cmdline 인자로 토큰을 포함시켜 _is_chat_executor_pid가 True를 반환하게 함
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)",
         "claude_worker.worker.chat_executor"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.3)  # 프로세스 시작 대기
        tmp_pid_file.write_text(str(proc.pid), encoding="utf-8")
        executor = _make_executor()
        with pytest.raises(SystemExit) as exc_info:
            executor._check_stale_pid()
        assert exc_info.value.code == 1
    finally:
        proc.kill()
        proc.wait()


def test_check_stale_pid_R_unrelated_real_process_treated_stale(tmp_pid_file):
    """T3: 실 subprocess에 무관한 cmdline → stale 처리 (sys.exit 미호출, PID 파일 제거)."""
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.3)
        tmp_pid_file.write_text(str(proc.pid), encoding="utf-8")
        executor = _make_executor()
        # sys.exit patch 없이 직접 호출 — SystemExit 없이 정상 반환되어야 함
        executor._check_stale_pid()
        assert not tmp_pid_file.exists()
    finally:
        proc.kill()
        proc.wait()
