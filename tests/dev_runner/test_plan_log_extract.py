"""plan 로그 추출(_try_extract_log) 단위 테스트."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.modules.dev_runner.services.daily_report_builder import _try_extract_log


# ── 이미 추출된 파일 존재 ───────────────────────────────────────────────────────

def test_try_extract_log_R_already_exists(tmp_path):
    """plan-runs/<runner_id>.log 이미 있으면 subprocess 호출 없이 경로 반환"""
    log_file = tmp_path / "abc123.log"
    log_file.write_text("log content", encoding="utf-8")

    with patch("app.modules.dev_runner.services.daily_report_builder._PLAN_RUNS_DIR", tmp_path), \
         patch("subprocess.run") as mock_run:
        result = _try_extract_log("abc123")

    mock_run.assert_not_called()
    assert result == str(log_file)


# ── 추출 스크립트 없음 ─────────────────────────────────────────────────────────

def test_try_extract_log_B_no_script(tmp_path):
    """extract-plan-log.ps1 없으면 빈 문자열 반환"""
    with patch("app.modules.dev_runner.services.daily_report_builder._PLAN_RUNS_DIR", tmp_path), \
         patch("app.modules.dev_runner.services.daily_report_builder._EXTRACT_SCRIPT",
               tmp_path / "nonexistent.ps1"):
        result = _try_extract_log("runner123")

    assert result == ""


# ── subprocess 성공 경로 ───────────────────────────────────────────────────────

def test_try_extract_log_R_script_success(tmp_path):
    """subprocess 성공 + 출력 파일 생성 → 경로 반환"""
    script = tmp_path / "extract-plan-log.ps1"
    script.write_text("# fake script", encoding="utf-8")
    out_file = tmp_path / "runner456.log"

    def fake_run(*args, **kwargs):
        out_file.write_text("extracted", encoding="utf-8")
        return MagicMock(returncode=0, stderr="")

    with patch("app.modules.dev_runner.services.daily_report_builder._PLAN_RUNS_DIR", tmp_path), \
         patch("app.modules.dev_runner.services.daily_report_builder._EXTRACT_SCRIPT", script), \
         patch("subprocess.run", side_effect=fake_run):
        result = _try_extract_log("runner456")

    assert result == str(out_file)


# ── subprocess 실패 경로 ───────────────────────────────────────────────────────

def test_try_extract_log_E_script_nonzero(tmp_path):
    """subprocess returncode != 0 → 빈 문자열"""
    script = tmp_path / "extract-plan-log.ps1"
    script.write_text("# fake script", encoding="utf-8")

    mock_result = MagicMock(returncode=1, stderr="marker not found")

    with patch("app.modules.dev_runner.services.daily_report_builder._PLAN_RUNS_DIR", tmp_path), \
         patch("app.modules.dev_runner.services.daily_report_builder._EXTRACT_SCRIPT", script), \
         patch("subprocess.run", return_value=mock_result):
        result = _try_extract_log("runnerBAD")

    assert result == ""


def test_try_extract_log_E_subprocess_exception(tmp_path):
    """subprocess 예외 발생 → 빈 문자열, 예외 전파 없음"""
    script = tmp_path / "extract-plan-log.ps1"
    script.write_text("# fake script", encoding="utf-8")

    with patch("app.modules.dev_runner.services.daily_report_builder._PLAN_RUNS_DIR", tmp_path), \
         patch("app.modules.dev_runner.services.daily_report_builder._EXTRACT_SCRIPT", script), \
         patch("subprocess.run", side_effect=TimeoutError("timeout")):
        result = _try_extract_log("runnerTIMEOUT")

    assert result == ""


# ── returncode=0 이지만 출력 파일 미생성 ──────────────────────────────────────

def test_try_extract_log_B_success_no_outfile(tmp_path):
    """subprocess 성공이지만 출력 파일 미생성 → 빈 문자열"""
    script = tmp_path / "extract-plan-log.ps1"
    script.write_text("# fake script", encoding="utf-8")
    mock_result = MagicMock(returncode=0, stderr="")

    with patch("app.modules.dev_runner.services.daily_report_builder._PLAN_RUNS_DIR", tmp_path), \
         patch("app.modules.dev_runner.services.daily_report_builder._EXTRACT_SCRIPT", script), \
         patch("subprocess.run", return_value=mock_result):
        result = _try_extract_log("runnerGHOST")

    assert result == ""
