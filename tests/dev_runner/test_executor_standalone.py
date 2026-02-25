import pytest
import re
from datetime import datetime

# Mock classes to simulate AIExecutor logic
class MockExecutionResult:
    def __init__(self, success, status, output, raw_output, model_used, error=None):
        self.success = success
        self.status = status
        self.output = output
        self.raw_output = raw_output
        self.model_used = model_used
        self.error = error

class AIExecutorStandalone:
    def _build_gemini_command(self, prompt, model=None, flags=None):
        cmd = ["gemini"]
        if model: cmd.extend(["--model", model])
        if flags: cmd.extend(flags)
        cmd.extend(["-p", prompt])
        return cmd

    def _extract_status_from_output(self, output):
        patterns = [r'STATUS:\s*(SUCCESS|FAILED|SKIPPED)', r'Status:\s*(SUCCESS|FAILED|SKIPPED)']
        for pattern in patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match: return match.group(1).lower()
        return None

    def _parse_gemini_output(self, stdout, stderr, returncode, model):
        success = returncode == 0
        status = self._extract_status_from_output(stdout) or ("success" if success else "failed")
        return MockExecutionResult(
            success=success, status=status, output=stdout, raw_output=stdout, model_used=model,
            error=f"Exit code: {returncode} | stderr: {stderr}" if not success else None
        )

    def _stream_gemini_line(self, line):
        clean_line = re.sub(r'\033\[[0-9;]*m', '', line)
        tag = "LINE"
        if "Tool use:" in clean_line or "Calling" in clean_line: tag = "TOOL"
        elif "Thinking:" in clean_line: tag = "THINK"
        return f"[{datetime.now().strftime('%H:%M:%S')}] [{tag}] {clean_line}"

def test_build_gemini_command():
    executor = AIExecutorStandalone()
    cmd = executor._build_gemini_command("hello", "gemini-3", ["--yolo"])
    assert cmd == ["gemini", "--model", "gemini-3", "--yolo", "-p", "hello"]

def test_parse_gemini_output_success():
    executor = AIExecutorStandalone()
    res = executor._parse_gemini_output("STATUS: SUCCESS", "", 0, "m1")
    assert res.success is True
    assert res.status == "success"

def test_parse_gemini_output_failure():
    executor = AIExecutorStandalone()
    res = executor._parse_gemini_output("some error", "api down", 1, "m1")
    assert res.success is False
    assert "Exit code: 1" in res.error

def test_stream_gemini_line_tagging():
    executor = AIExecutorStandalone()
    res = executor._stream_gemini_line("Calling tool: ReadFile")
    assert "[TOOL]" in res
    res = executor._stream_gemini_line("Thinking: logic...")
    assert "[THINK]" in res
