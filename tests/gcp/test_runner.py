"""TC: _runner.py — RIGHT-BICEP coverage (subprocess mocked)."""

from unittest.mock import MagicMock, patch

import pytest

from scripts.gcp._runner import (
    CmdResult,
    CostGuardBlocked,
    cost_guard,
    resource_exists,
    run_cmd,
)


def test_run_cmd_R_dry_run_no_exec():
    """R: dry_run=True → subprocess NOT called, command string returned."""
    with patch("scripts.gcp._runner.subprocess.run") as mock_run:
        result = run_cmd(["gcloud", "info"], dry_run=True)
    mock_run.assert_not_called()
    assert result.dry_run is True
    assert result.returncode == 0
    assert "gcloud" in result.stdout
    assert isinstance(result.cmd, list)


def test_run_cmd_R_apply_calls_subprocess():
    """R: dry_run=False → subprocess called with given args."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "ok"
    mock_result.stderr = ""
    with patch("scripts.gcp._runner.subprocess.run", return_value=mock_result) as mock_run:
        result = run_cmd(["gcloud", "info"], dry_run=False)
    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]
    assert call_args == ["gcloud", "info"]
    assert result.dry_run is False
    assert result.returncode == 0


def test_resource_exists_R_present():
    """R: describe returns returncode=0 → True."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    with patch("scripts.gcp._runner.subprocess.run", return_value=mock_result):
        assert resource_exists(["bq", "show", "proj:dataset"]) is True


def test_resource_exists_B_absent():
    """B: describe returns returncode=1 (not-found) → False."""
    mock_result = MagicMock()
    mock_result.returncode = 1
    with patch("scripts.gcp._runner.subprocess.run", return_value=mock_result):
        assert resource_exists(["bq", "show", "proj:dataset"]) is False


def test_cost_guard_E_flag_false_raises():
    """E: flag=False → CostGuardBlocked raised."""
    with pytest.raises(CostGuardBlocked) as exc_info:
        cost_guard("ENABLE_CLOUD_BUILD", False)
    assert "ENABLE_CLOUD_BUILD" in str(exc_info.value)


def test_cost_guard_R_flag_true_passes():
    """R: flag=True → no exception."""
    cost_guard("ENABLE_CLOUD_BUILD", True)  # should not raise
