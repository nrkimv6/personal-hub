"""Phase T1: TC for scripts/gcp/secret_manager.py — RIGHT-BICEP.

All tests are dry-run/mock only — no real gcloud commands are executed and
no live GCP calls are made.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scripts.gcp._config import GcpConfig
from scripts.gcp._runner import CostGuardBlocked
from scripts.gcp.secret_manager import SECRET_NAMES, add_secret_version, provision_secrets


def _make_cfg(enable_sm: bool = False) -> GcpConfig:
    return GcpConfig(
        project_id="test-project",
        region="asia-northeast3",
        dataset_name="personal_hub_events",
        ar_repo_name="test-repo",
        cloud_run_service="test-service",
        enable_secret_manager=enable_sm,
    )


# ---------------------------------------------------------------------------
# R: Right — dry_run=True → 7 create commands returned, subprocess NOT called
# ---------------------------------------------------------------------------

def test_provision_secrets_R_dry_run_commands():
    """R: dry_run=True → 7 CmdResult objects with gcloud secrets create, no subprocess."""
    cfg = _make_cfg(enable_sm=True)

    with patch("scripts.gcp._runner.subprocess.run") as mock_run:
        results = provision_secrets(cfg, dry_run=True)

    mock_run.assert_not_called()
    assert len(results) == len(SECRET_NAMES), "Expected one result per secret name"
    all_cmds = " ".join(" ".join(r.cmd) for r in results)
    assert "gcloud" in all_cmds
    assert "secrets" in all_cmds
    assert "create" in all_cmds
    for name in SECRET_NAMES:
        assert name in all_cmds, f"{name} not found in dry-run command output"


def test_provision_secrets_R_dry_run_flag_set():
    """R: each CmdResult has dry_run=True when dry_run=True."""
    cfg = _make_cfg(enable_sm=True)
    results = provision_secrets(cfg, dry_run=True)
    assert all(r.dry_run is True for r in results)


# ---------------------------------------------------------------------------
# B: Boundary — idempotency: existing secrets are skipped
# ---------------------------------------------------------------------------

def test_provision_secrets_B_idempotent_skip(capsys):
    """B: resource_exists() mock returns True → create command skipped."""
    cfg = _make_cfg(enable_sm=True)

    with patch("scripts.gcp.secret_manager.resource_exists", return_value=True):
        # dry_run=False so resource_exists is actually called
        with patch("scripts.gcp._runner.subprocess.run") as mock_run:
            results = provision_secrets(cfg, dry_run=False)

    # All secrets already exist → no create commands should be in results
    assert results == [], "Expected empty results when all secrets already exist"
    mock_run.assert_not_called()

    captured = capsys.readouterr()
    # Should see skip messages
    assert "[skip]" in captured.out


def test_provision_secrets_B_partial_idempotent(capsys):
    """B: resource_exists() returns True for first half, False for second half."""
    cfg = _make_cfg(enable_sm=True)
    half = len(SECRET_NAMES) // 2
    side_effects = [True] * half + [False] * (len(SECRET_NAMES) - half)

    with patch("scripts.gcp.secret_manager.resource_exists", side_effect=side_effects):
        with patch("scripts.gcp._runner.subprocess.run") as mock_run:
            results = provision_secrets(cfg, dry_run=False)

    assert len(results) == len(SECRET_NAMES) - half


# ---------------------------------------------------------------------------
# E: Error — ENABLE_SECRET_MANAGER=false → CostGuardBlocked
# ---------------------------------------------------------------------------

def test_provision_secrets_E_cost_guard_blocks():
    """E: enable_secret_manager=False → CostGuardBlocked raised."""
    cfg = _make_cfg(enable_sm=False)

    with pytest.raises(CostGuardBlocked) as exc_info:
        provision_secrets(cfg, dry_run=True)

    assert "ENABLE_SECRET_MANAGER" in str(exc_info.value)


# ---------------------------------------------------------------------------
# I: Inverse — no real secret values in commands
# ---------------------------------------------------------------------------

def test_provision_secrets_I_no_real_values():
    """I: Placeholder/secret values never appear in gcloud command arguments."""
    cfg = _make_cfg(enable_sm=True)
    results = provision_secrets(cfg, dry_run=True)

    # The create command should only contain the secret NAME, never a secret value.
    for result in results:
        cmd_str = " ".join(result.cmd)
        # Commands must NOT contain --data-file with a real value
        # (add_secret_version is a separate function)
        assert "--data-file" not in cmd_str
        assert "PLACEHOLDER" not in cmd_str


def test_add_secret_version_I_placeholder_only():
    """I: add_secret_version dry-run command contains --data-file=- not a real value."""
    cfg = _make_cfg(enable_sm=True)
    result = add_secret_version("JWT_SECRET", cfg, value_placeholder="real-value", dry_run=True)

    cmd_str = " ".join(result.cmd)
    assert "--data-file=-" in cmd_str
    # The placeholder value itself is NOT injected into the gcloud command args
    assert "real-value" not in cmd_str


def test_add_secret_version_R_dry_run():
    """R: add_secret_version dry_run=True → returns CmdResult without subprocess."""
    cfg = _make_cfg(enable_sm=True)

    with patch("scripts.gcp._runner.subprocess.run") as mock_run:
        result = add_secret_version("TELEGRAM_BOT_TOKEN", cfg, dry_run=True)

    mock_run.assert_not_called()
    assert result.dry_run is True
    assert "TELEGRAM_BOT_TOKEN" in result.cmd
    assert "--data-file=-" in result.cmd
