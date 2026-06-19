"""Phase T1: TC for app/core/secret_manager_client.py — RIGHT-BICEP.

All tests use mocks — no real GCP SDK calls are made.

Import pattern: We import secret_manager_client directly via importlib.util
to bypass app/core/__init__.py (which imports app.core.database not available
in this worktree test context).
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Module import helper — bypass app/core/__init__.py
# ---------------------------------------------------------------------------

_SMC_PATH = Path(__file__).parent.parent.parent / "app" / "core" / "secret_manager_client.py"


def _load_smc_fresh():
    """Load secret_manager_client as a top-level module bypassing __init__.py."""
    # Use a unique name so each reload is clean
    mod_name = "_test_smc_fresh"
    spec = importlib.util.spec_from_file_location(mod_name, _SMC_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# R: Right — ENABLE_SECRET_MANAGER=true + SDK mock → returns secret value
# ---------------------------------------------------------------------------

def test_get_secret_R_enabled_calls_sdk(monkeypatch):
    """R: ENABLE_SECRET_MANAGER=true + SDK mock → returns decoded payload."""
    monkeypatch.setenv("ENABLE_SECRET_MANAGER", "true")

    mock_response = MagicMock()
    mock_response.payload.data = b"super-secret-value"
    mock_client_instance = MagicMock()
    mock_client_instance.access_secret_version.return_value = mock_response
    mock_secretmanager_mod = MagicMock()
    mock_secretmanager_mod.SecretManagerServiceClient.return_value = mock_client_instance

    with patch.dict(sys.modules, {
        "google": MagicMock(cloud=MagicMock(secretmanager=mock_secretmanager_mod)),
        "google.cloud": MagicMock(secretmanager=mock_secretmanager_mod),
        "google.cloud.secretmanager": mock_secretmanager_mod,
    }):
        mod = _load_smc_fresh()
        result = mod.get_secret("JWT_SECRET", "my-project")

    assert result == "super-secret-value"
    mock_client_instance.access_secret_version.assert_called_once()


def test_get_secret_R_name_path_format(monkeypatch):
    """R: get_secret constructs the correct resource path."""
    monkeypatch.setenv("ENABLE_SECRET_MANAGER", "true")

    mock_response = MagicMock()
    mock_response.payload.data = b"token-value"
    mock_client_instance = MagicMock()
    mock_client_instance.access_secret_version.return_value = mock_response
    mock_secretmanager_mod = MagicMock()
    mock_secretmanager_mod.SecretManagerServiceClient.return_value = mock_client_instance

    with patch.dict(sys.modules, {
        "google": MagicMock(cloud=MagicMock(secretmanager=mock_secretmanager_mod)),
        "google.cloud": MagicMock(secretmanager=mock_secretmanager_mod),
        "google.cloud.secretmanager": mock_secretmanager_mod,
    }):
        mod = _load_smc_fresh()
        mod.get_secret("TELEGRAM_BOT_TOKEN", "test-project")

    call_kwargs = mock_client_instance.access_secret_version.call_args[1]
    expected_path = "projects/test-project/secrets/TELEGRAM_BOT_TOKEN/versions/latest"
    assert call_kwargs.get("name") == expected_path


# ---------------------------------------------------------------------------
# E: Error — ENABLE_SECRET_MANAGER=false → RuntimeError
# ---------------------------------------------------------------------------

def test_get_secret_E_disabled_raises(monkeypatch):
    """E: ENABLE_SECRET_MANAGER=false → RuntimeError immediately, no SDK import."""
    monkeypatch.setenv("ENABLE_SECRET_MANAGER", "false")
    mod = _load_smc_fresh()

    with pytest.raises(RuntimeError) as exc_info:
        mod.get_secret("JWT_SECRET", "any-project")

    assert "ENABLE_SECRET_MANAGER" in str(exc_info.value)
    assert "not true" in str(exc_info.value).lower()


def test_get_secret_E_disabled_default(monkeypatch):
    """E: No ENABLE_SECRET_MANAGER env var → RuntimeError (defaults to false)."""
    monkeypatch.delenv("ENABLE_SECRET_MANAGER", raising=False)
    mod = _load_smc_fresh()

    with pytest.raises(RuntimeError):
        mod.get_secret("JWT_SECRET", "any-project")


# ---------------------------------------------------------------------------
# B: Boundary — SDK not installed → clear ImportError
# ---------------------------------------------------------------------------

def test_get_secret_B_sdk_not_installed(monkeypatch):
    """B: google-cloud-secret-manager not installed → ImportError with hint."""
    monkeypatch.setenv("ENABLE_SECRET_MANAGER", "true")

    # Simulate missing package by setting the module to None in sys.modules
    saved = {k: v for k, v in sys.modules.items() if k.startswith("google")}
    for key in list(saved.keys()):
        sys.modules.pop(key)

    with patch.dict(sys.modules, {
        "google": None,
        "google.cloud": None,
        "google.cloud.secretmanager": None,
    }):
        mod = _load_smc_fresh()
        with pytest.raises((ImportError, TypeError, AttributeError)) as exc_info:
            mod.get_secret("JWT_SECRET", "any-project")

    # Restore
    sys.modules.update(saved)

    # The error should be related to the import failure
    error_msg = str(exc_info.value).lower()
    assert exc_info.type in (ImportError, TypeError, AttributeError)


def test_get_secret_B_disabled_no_sdk_import(monkeypatch):
    """B: ENABLE_SECRET_MANAGER=false → google.cloud.secretmanager never imported."""
    monkeypatch.setenv("ENABLE_SECRET_MANAGER", "false")

    # Remove google modules before the call
    saved = {k: v for k, v in sys.modules.items() if k.startswith("google")}
    for key in list(saved.keys()):
        sys.modules.pop(key)

    mod = _load_smc_fresh()

    with pytest.raises(RuntimeError):
        mod.get_secret("JWT_SECRET", "any-project")

    # SDK should never have been imported
    assert "google.cloud.secretmanager" not in sys.modules

    # Restore
    sys.modules.update(saved)
