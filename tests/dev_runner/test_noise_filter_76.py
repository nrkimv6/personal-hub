"""7.6: gemini 노이즈 라인 필터 검증

억제 대상:
  - xterm.js: Parsing error: {...} 블록
  - node-pty AttachConsole failed 스택트레이스

동작:
  - 파일 기록(log_handle.write)은 노이즈 포함 전체 유지
  - Redis publish는 노이즈 라인 억제, 정상 라인 직전에 요약 1줄 publish
  - rate-limiter: 동일 내용 burst 반복 시 억제
"""
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# listener_noise_filter는 scripts/ 디렉토리에 위치
_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from listener_noise_filter import NOISE_BLOCK_MARKERS, is_noise_line


@pytest.fixture(autouse=True)
def _real_is_noise_line(monkeypatch):
    """모듈 레벨에서 is_noise_line이 mock에 바인딩된 경우에도 실제 함수를 사용한다."""
    import importlib
    import tests.dev_runner.test_noise_filter_76 as _this_module
    sys.modules.pop("listener_noise_filter", None)
    real = importlib.import_module("listener_noise_filter")
    monkeypatch.setattr(_this_module, "is_noise_line", real.is_noise_line)


def _make_process_stub(lines: list):
    proc = MagicMock()
    stdout = MagicMock()
    stdout.readline.side_effect = [line + "\n" for line in lines] + [""]
    proc.stdout = stdout
    proc.returncode = 0
    proc.wait = MagicMock(return_value=0)
    return proc


def _run_stream(lines: list):
    """_stream_output 직접 호출 → (published_messages, written_lines) 반환"""
    # listener 모듈 로드 (redis는 mock으로 대체)
    import unittest.mock as um
    _redis_mock = um.MagicMock()
    sys.modules.setdefault("redis", _redis_mock)

    # 다른 테스트가 오염시킨 listener_noise_filter mock을 sys.modules에서 제거
    # (test_command_listener_multi_runner.py가 is_noise_line=lambda: False로 mock 오염)
    sys.modules.pop("listener_noise_filter", None)
    sys.modules.pop("_dr_plan_runner", None)
    sys.modules.pop("_dr_process_utils", None)
    sys.modules.pop("_listener_under_test", None)

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_listener_under_test",
        str(_SCRIPTS_DIR / "dev-runner-command-listener.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        pass  # 전역 초기화 실패 무시 (함수만 사용)

    # 이전 테스트에서 오염된 프로세스 상태 초기화 (self-join RuntimeError 방지)
    if hasattr(mod, '_running_processes'):
        mod._running_processes.clear()
    if hasattr(mod, '_stream_threads'):
        mod._stream_threads.clear()

    _stream_output = getattr(mod, "_stream_output", None)
    if _stream_output is None:
        pytest.skip("_stream_output 로드 실패")

    published = []
    written = []

    proc = _make_process_stub(lines)
    mock_log = MagicMock()
    mock_log.write.side_effect = lambda s: written.append(s)

    mock_redis = MagicMock()
    mock_redis.publish.side_effect = lambda ch, msg: published.append(msg)
    # 기본 MagicMock 반환값이 cleanup 경로 분기를 오염시키지 않도록 고정
    mock_redis.get.side_effect = lambda *_args, **_kwargs: None
    mock_redis.set.return_value = True
    mock_redis.delete.return_value = 0
    mock_redis.expire.return_value = True
    mock_redis.persist.return_value = True
    mock_redis.srem.return_value = 0
    mock_redis.zadd.return_value = 1
    mock_redis.lrem.return_value = 0

    _stream_output(proc, mock_log, mock_redis, runner_id="t-noise-runner")
    return published, written


def _flatten_user_lines(published: list[str]) -> list[str]:
    """테스트 대상 로그 라인만 추출 (제어 메시지 제외)."""
    lines: list[str] = []
    for message in published:
        if message.startswith("__COMPLETED::"):
            continue
        if message.startswith("[CLEANUP]"):
            continue
        for line in message.split("\n"):
            if line:
                lines.append(line)
    return lines


# ── is_noise_line 단위 테스트 ────────────────────────────────────────────────

class TestIsNoiseLine:
    def test_xterm_parsing_error_suppressed(self):
        assert is_noise_line("xterm.js: Parsing error: {")

    def test_xterm_generic_suppressed(self):
        assert is_noise_line("xterm.js: some message")

    def test_attach_console_suppressed(self):
        assert is_noise_line("Error: AttachConsole failed")

    def test_at_stacktrace_suppressed(self):
        assert is_noise_line("    at Object.<anonymous> (file.js:1:1)")

    def test_nodejs_version_suppressed(self):
        assert is_noise_line("Node.js v24.7.0")

    def test_node_pty_path_suppressed(self):
        """node-pty conpty 경로 줄은 억제 대상"""
        line = r"C:\Users\...\node_modules\@lydell\node-pty\conpty_console_list_agent.js:11"
        assert is_noise_line(line)

    def test_normal_line_not_suppressed(self):
        assert not is_noise_line("[Claude] 작업 시작")

    def test_empty_line_not_suppressed(self):
        assert not is_noise_line("")

    def test_korean_line_not_suppressed(self):
        assert not is_noise_line("BOM이 제거되었는지 확인합니다")

    def test_stderr_prefixed_xterm_suppressed(self):
        """plan-runner가 '[ts] [STDERR] xterm.js:...' 형태로 감싼 경우도 억제"""
        assert is_noise_line("  [20:03:37] [STDERR] xterm.js: Parsing error: {")

    def test_stderr_prefixed_attach_console_suppressed(self):
        assert is_noise_line("  [20:03:37] [STDERR] Error: AttachConsole failed")

    def test_stderr_prefixed_at_stacktrace_suppressed(self):
        assert is_noise_line("  [20:03:37] [STDERR]     at Object.<anonymous> (file.js:1:1)")

    def test_stderr_prefixed_nodejs_version_suppressed(self):
        assert is_noise_line("  [20:03:37] [STDERR] Node.js v24.7.0")

    def test_stderr_prefixed_normal_line_not_suppressed(self):
        assert not is_noise_line("  [20:03:37] [STDERR] BOM이 제거되었습니다")

    # ── xterm.js JSON 바디 줄 ───────────────────────────────────────────────
    def test_xterm_json_numbers_suppressed(self):
        assert is_noise_line("  [20:12:15] [STDERR]        0, 0, 0, 0, 0")

    def test_xterm_json_closing_bracket_suppressed(self):
        assert is_noise_line("  [20:12:15] [STDERR]     ],")

    def test_xterm_json_length_prop_suppressed(self):
        assert is_noise_line("  [20:12:15] [STDERR]     length: 2,")

    def test_xterm_json_sub_params_suppressed(self):
        assert is_noise_line("  [20:12:15] [STDERR]     _subParams: Int32Array(32) [")

    def test_xterm_json_reject_digits_suppressed(self):
        assert is_noise_line("  [20:12:15] [STDERR]     _rejectDigits: false,")

    def test_xterm_json_abort_suppressed(self):
        assert is_noise_line("  [20:12:15] [STDERR]   abort: false")

    def test_xterm_json_uint32array_suppressed(self):
        assert is_noise_line("  [20:12:15] [STDERR]     _subParamsIdx: Uint16Array(32) [")

    # ── conpty / node-pty 경로 및 관련 줄 ──────────────────────────────────
    def test_conpty_path_suppressed(self):
        line = r"  [20:18:54] [STDERR] C:\Users\Narang\AppData\Roaming\npm\node_modules\@google\gemini-cli\node_modules\@lydell\node-pty\conpty_console_list_agent.js:11"
        assert is_noise_line(line)

    def test_var_console_process_list_suppressed(self):
        assert is_noise_line("  [20:18:54] [STDERR] var consoleProcessList = getConsoleProcessList(shellPid);")

    def test_caret_pointer_suppressed(self):
        assert is_noise_line("  [20:18:54] [STDERR]                          ^")

    def test_caret_only_suppressed(self):
        assert is_noise_line("  [20:18:54] [STDERR] ^")


# ── _stream_output 통합 테스트 ───────────────────────────────────────────────

class TestStreamOutputFilter:

    def test_normal_lines_published(self):
        published, _ = _run_stream(["정상 로그 A", "정상 로그 B"])
        lines = _flatten_user_lines(published)
        assert "정상 로그 A" in lines
        assert "정상 로그 B" in lines

    def test_xterm_noise_not_published(self):
        published, written = _run_stream([
            "xterm.js: Parsing error: {",
            "  position: 1186,",
            "  code: 20108",
            "}",
            "정상 로그",
        ])
        lines = _flatten_user_lines(published)
        assert not any("xterm.js" in p for p in lines), "xterm.js 줄 publish 안 됨"
        assert any("lines suppressed" in p for p in lines), "억제 요약 publish"
        assert "정상 로그" in lines

    def test_attach_console_not_published(self):
        published, _ = _run_stream([
            "Error: AttachConsole failed",
            "    at Object.<anonymous> (conpty_console_list_agent.js:11:26)",
            "    at Module._compile (node:internal/modules/cjs/loader:1738:14)",
            "Node.js v24.7.0",
            "작업 시작",
        ])
        lines = _flatten_user_lines(published)
        assert not any("AttachConsole" in p for p in lines)
        assert not any("at Object.<anonymous>" in p for p in lines)
        assert not any("Node.js v" in p for p in lines)
        assert any("lines suppressed" in p for p in lines)
        assert "작업 시작" in lines

    def test_noise_lines_still_written_to_file(self):
        _, written = _run_stream([
            "xterm.js: Parsing error: {",
            "  position: 1186",
            "}",
        ])
        combined = "".join(written)
        assert "xterm.js" in combined, "파일에는 노이즈 라인도 기록"

    def test_suppression_summary_single_line(self):
        noise = ["xterm.js: Parsing error: {"] * 50 + ["정상"]
        published, _ = _run_stream(noise)
        summary_lines = [p for p in _flatten_user_lines(published) if "lines suppressed" in p]
        assert len(summary_lines) == 1, f"요약은 1줄: {summary_lines}"

    def test_rate_limiter_burst(self):
        same_line = "반복 에러"
        lines = [same_line] * 30 + ["다른 정상 로그"]
        published, _ = _run_stream(lines)
        repeat_publishes = [p for p in published if p == same_line]
        assert len(repeat_publishes) <= 10, f"burst 억제 미작동: {len(repeat_publishes)}회"
        assert any("다른 정상 로그" in p for p in published)

    def test_multiline_result_is_framed_as_single_publish(self):
        published, _ = _run_stream([
            "[12:00:00] [RESULT] line-1",
            "line-2",
            "line-3",
            "[12:00:01] [AI] done",
        ])
        framed = [p for p in published if "[RESULT] line-1" in p]
        assert len(framed) == 1, f"RESULT 프레임이 단일 publish가 아님: {published}"
        assert "line-2" in framed[0]
        assert "line-3" in framed[0]
        assert "line-2" not in [p for p in published if p == "line-2"]
