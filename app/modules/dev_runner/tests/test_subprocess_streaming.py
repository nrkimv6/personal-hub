"""_run_subprocess_streaming 헬퍼 + conflict resolver / auto-fix 스트리밍 테스트

listener 스크립트는 하이픈이 포함된 파일명으로 직접 import 불가하므로,
importlib를 사용하여 로드한다.
"""

import importlib.util
import sys
import time
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_LISTENER_PATH = (
    Path(__file__).parent.parent.parent.parent.parent / "scripts" / "dev-runner-command-listener.py"
)


def _load_listener():
    """dev-runner-command-listener.py를 importlib로 직접 로드"""
    spec = importlib.util.spec_from_file_location("_listener", str(_LISTENER_PATH))
    mod = importlib.util.module_from_spec(spec)
    # listener 초기화 시 Redis/sys.path 의존 모듈 로드를 막기 위해 mock 주입
    sys.modules.setdefault("redis", MagicMock())
    sys.modules.setdefault("fakeredis", MagicMock())
    try:
        spec.loader.exec_module(mod)
    except Exception:
        pass  # 초기화 중 일부 예외는 무시 (Redis 연결 등)
    return mod


# ── 헬퍼: 가짜 프로세스 ──────────────────────────────────────────────────────

class _FakeProc:
    """subprocess.Popen 흉내 — 미리 정한 출력 라인을 yield"""

    def __init__(self, lines: list[str], returncode: int = 0):
        self.stdout = iter(l + "\n" for l in lines)
        self.returncode = returncode

    def wait(self):
        pass

    def kill(self):
        pass


# ── _run_subprocess_streaming (로직 직접 복제 테스트) ───────────────────────

def _run_subprocess_streaming_impl(cmd, env, cwd, pub_fn, tag, timeout=300):
    """listener의 _run_subprocess_streaming 로직 직접 복제 (import 우회)"""
    import subprocess as _sp

    output_lines: list[str] = []
    timed_out = False
    _timer = None

    try:
        proc = _sp.Popen(
            cmd,
            cwd=cwd,
            stdout=_sp.PIPE,
            stderr=_sp.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

        def _kill():
            nonlocal timed_out
            timed_out = True
            try:
                proc.kill()
            except Exception:
                pass

        _timer = threading.Timer(timeout, _kill)
        _timer.start()

        for line in proc.stdout:
            stripped = line.rstrip()
            output_lines.append(stripped)
            if pub_fn and stripped:
                try:
                    pub_fn(f"[{tag}] {stripped}")
                except Exception:
                    pass

        proc.wait()

    except Exception as e:
        if _timer:
            _timer.cancel()
        return {"success": False, "message": str(e), "output": "\n".join(output_lines)}
    finally:
        if _timer:
            _timer.cancel()

    if timed_out:
        return {"success": False, "message": f"{tag} timeout ({timeout}s)", "output": "\n".join(output_lines)}

    output_text = "\n".join(output_lines)
    if proc.returncode == 0:
        return {"success": True, "message": f"{tag} 성공", "output": output_text}

    error_lines = [l.strip() for l in output_lines if l.strip() and ("Error" in l or "Exception" in l)]
    if error_lines:
        msg = error_lines[-1][:300]
    else:
        non_empty = [l.strip() for l in output_lines if l.strip() and not l.strip().startswith(("│", "┌", "└", "├", "─"))]
        msg = "; ".join(non_empty[-3:])[:300] if non_empty else f"exit code {proc.returncode}"
    return {"success": False, "message": msg, "output": output_text}


class TestRunSubprocessStreaming:
    """_run_subprocess_streaming 로직 단위 테스트"""

    def test_success_publishes_each_line(self):
        """R(Right): 정상 출력 시 pub_fn이 라인별 호출되고 success=True 반환"""
        published = []

        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = _FakeProc(["line1", "line2", "line3"], returncode=0)
            result = _run_subprocess_streaming_impl(
                cmd=["echo", "hi"], env={}, cwd="/tmp",
                pub_fn=lambda msg: published.append(msg),
                tag="TEST",
            )

        assert result["success"] is True
        assert len(published) == 3
        assert all("[TEST]" in m for m in published)
        assert "line1" in published[0]

    def test_failure_returns_success_false(self):
        """R(Right): returncode != 0 시 success=False + 에러 메시지"""
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = _FakeProc(["SomeError: bad"], returncode=1)
            result = _run_subprocess_streaming_impl(
                cmd=["bad"], env={}, cwd="/tmp", pub_fn=None, tag="T"
            )

        assert result["success"] is False
        assert "SomeError" in result["message"]

    def test_empty_output_pub_fn_not_called(self):
        """B(Boundary): 출력 없는 프로세스 → pub_fn 미호출, success=True"""
        published = []

        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = _FakeProc([], returncode=0)
            result = _run_subprocess_streaming_impl(
                cmd=["true"], env={}, cwd="/tmp",
                pub_fn=lambda m: published.append(m),
                tag="T",
            )

        assert result["success"] is True
        assert published == []

    def test_pub_fn_none_no_error(self):
        """E(Error): pub_fn=None 시 에러 없이 동작"""
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = _FakeProc(["hello"], returncode=0)
            result = _run_subprocess_streaming_impl(
                cmd=["echo"], env={}, cwd="/tmp", pub_fn=None, tag="T"
            )

        assert result["success"] is True

    def test_pub_fn_raises_continues(self):
        """E(Error): pub_fn이 예외를 발생시켜도 나머지 라인 처리 계속"""
        call_count = [0]

        def bad_pub(msg):
            call_count[0] += 1
            raise RuntimeError("pub error")

        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = _FakeProc(["a", "b", "c"], returncode=0)
            result = _run_subprocess_streaming_impl(
                cmd=["echo"], env={}, cwd="/tmp", pub_fn=bad_pub, tag="T"
            )

        assert result["success"] is True
        assert call_count[0] == 3  # 예외에도 계속 호출

    def test_timeout_kills_and_returns_failure(self):
        """B(Boundary): timeout 초과 시 프로세스 kill + success=False"""
        import subprocess as _sp

        killed = []

        class SlowProc:
            stdout = iter([])
            returncode = -9

            def wait(self):
                time.sleep(10)

            def kill(self):
                killed.append(True)

        with patch("subprocess.Popen", return_value=SlowProc()):
            result = _run_subprocess_streaming_impl(
                cmd=["sleep", "10"], env={}, cwd="/tmp",
                pub_fn=None, tag="T", timeout=1,
            )

        assert result["success"] is False
        assert "timeout" in result["message"].lower()
