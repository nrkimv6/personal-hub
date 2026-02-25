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


def _make_process_stub(lines: list):
    proc = MagicMock()
    proc.stdout = iter(line + "\n" for line in lines)
    proc.returncode = 0
    proc.wait = MagicMock(return_value=0)
    return proc


def _run_stream(lines: list):
    """_stream_output 직접 호출 → (published_messages, written_lines) 반환"""
    # listener 모듈 로드 (redis는 mock으로 대체)
    import unittest.mock as um
    _redis_mock = um.MagicMock()
    sys.modules.setdefault("redis", _redis_mock)

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

    _stream_output(proc, mock_log, mock_redis)
    return published, written


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
        assert "정상 로그 A" in published
        assert "정상 로그 B" in published

    def test_xterm_noise_not_published(self):
        published, written = _run_stream([
            "xterm.js: Parsing error: {",
            "  position: 1186,",
            "  code: 20108",
            "}",
            "정상 로그",
        ])
        assert not any("xterm.js" in p for p in published), "xterm.js 줄 publish 안 됨"
        assert any("noise lines suppressed" in p for p in published), "억제 요약 publish"
        assert "정상 로그" in published

    def test_attach_console_not_published(self):
        published, _ = _run_stream([
            "Error: AttachConsole failed",
            "    at Object.<anonymous> (conpty_console_list_agent.js:11:26)",
            "    at Module._compile (node:internal/modules/cjs/loader:1738:14)",
            "Node.js v24.7.0",
            "작업 시작",
        ])
        assert not any("AttachConsole" in p for p in published)
        assert not any("at Object.<anonymous>" in p for p in published)
        assert not any("Node.js v" in p for p in published)
        assert any("noise lines suppressed" in p for p in published)
        assert "작업 시작" in published

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
        summary_lines = [p for p in published if "noise lines suppressed" in p]
        assert len(summary_lines) == 1, f"요약은 1줄: {summary_lines}"

    def test_rate_limiter_burst(self):
        same_line = "반복 에러"
        lines = [same_line] * 30 + ["다른 정상 로그"]
        published, _ = _run_stream(lines)
        repeat_publishes = [p for p in published if p == same_line]
        assert len(repeat_publishes) <= 10, f"burst 억제 미작동: {len(repeat_publishes)}회"
        assert "다른 정상 로그" in published
