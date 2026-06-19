"""Phase T1: TC for app/core/config.py Secret Manager fallback — RIGHT-BICEP.

Tests the _load_secret() helper function and the load_secrets root_validator.
All tests use mocks — no real GCP calls are made.

Import pattern: We import config directly via importlib.util to bypass
app/core/__init__.py (which imports app.core.database not available in this
worktree test context).
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

_CONFIG_PATH = Path(__file__).parent.parent.parent / "app" / "core" / "config.py"
_SMC_PATH = Path(__file__).parent.parent.parent / "app" / "core" / "secret_manager_client.py"


def _load_config_fresh():
    """Load config.py as a standalone module bypassing __init__.py."""
    mod_name = "_test_config_fresh"
    spec = importlib.util.spec_from_file_location(mod_name, _CONFIG_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_smc_fresh():
    """Load secret_manager_client.py standalone."""
    mod_name = "_test_smc_fresh2"
    spec = importlib.util.spec_from_file_location(mod_name, _SMC_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# R: Right — env fallback path
# ---------------------------------------------------------------------------

def test_load_secret_R_env_fallback(monkeypatch):
    """R: sm_enabled=False → returns os.environ[env_key] value."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-token-from-env")

    mod = _load_config_fresh()
    result = mod._load_secret("TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN", sm_enabled=False)

    assert result == "bot-token-from-env"


def test_load_secret_R_env_fallback_empty(monkeypatch):
    """R: sm_enabled=False + env not set → returns empty string."""
    monkeypatch.delenv("SOME_MISSING_KEY_XYZ", raising=False)

    mod = _load_config_fresh()
    result = mod._load_secret("SOME_MISSING_KEY_XYZ", "SOME_MISSING_KEY_XYZ", sm_enabled=False)

    assert result == ""


def test_load_secret_R_sm_priority(monkeypatch):
    """R: sm_enabled=True + mocked get_secret → Secret Manager value returned."""
    monkeypatch.setenv("JWT_SECRET", "env-jwt-fallback")
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")

    # Load the SMC module fresh and patch its function
    smc_mod = _load_smc_fresh()
    smc_mod.get_secret = lambda name, pid: "sm-jwt-value"

    # Load config fresh, then patch its get_secret import
    mod = _load_config_fresh()
    # Monkey-patch the lazy import inside _load_secret
    original_import = mod.__builtins__["__import__"] if isinstance(mod.__builtins__, dict) else __builtins__.__import__

    def mock_import(name, *args, **kwargs):
        if name == "app.core.secret_manager_client":
            return smc_mod
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        result = mod._load_secret("JWT_SECRET", "JWT_SECRET", sm_enabled=True)

    assert result == "sm-jwt-value"


# ---------------------------------------------------------------------------
# E: Error — Secret Manager failure → env fallback
# ---------------------------------------------------------------------------

def test_load_secret_E_sm_fail_env_fallback(monkeypatch):
    """E: get_secret raises exception → falls back to env var."""
    monkeypatch.setenv("EMAIL_ADDRESS", "fallback@example.com")
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")

    smc_mod = _load_smc_fresh()
    smc_mod.get_secret = MagicMock(side_effect=Exception("GCP unavailable"))

    mod = _load_config_fresh()
    original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else None

    def mock_import(name, *args, **kwargs):
        if name == "app.core.secret_manager_client":
            return smc_mod
        if original_import:
            return original_import(name, *args, **kwargs)
        return __import__(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        result = mod._load_secret("EMAIL_ADDRESS", "EMAIL_ADDRESS", sm_enabled=True)

    assert result == "fallback@example.com"


def test_load_secret_E_sm_fail_no_env_empty(monkeypatch):
    """E: Secret Manager failure + no env var → empty string (no crash)."""
    monkeypatch.delenv("SOME_MISSING_KEY_ABC", raising=False)
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")

    smc_mod = _load_smc_fresh()
    smc_mod.get_secret = MagicMock(side_effect=RuntimeError("disabled"))

    mod = _load_config_fresh()
    original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else None

    def mock_import(name, *args, **kwargs):
        if name == "app.core.secret_manager_client":
            return smc_mod
        if original_import:
            return original_import(name, *args, **kwargs)
        return __import__(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        result = mod._load_secret("SOME_MISSING_KEY_ABC", "SOME_MISSING_KEY_ABC", sm_enabled=True)

    assert result == ""


# ---------------------------------------------------------------------------
# P: Performance/cost — no SDK import when disabled
# ---------------------------------------------------------------------------

def test_config_P_no_sdk_import_when_disabled(monkeypatch):
    """P: sm_enabled=False → google.cloud.secretmanager NOT imported."""
    monkeypatch.setenv("ENABLE_SECRET_MANAGER", "false")
    monkeypatch.setenv("JWT_SECRET", "some-value")

    # Remove google modules before calling _load_secret
    saved = {k: v for k, v in sys.modules.items() if k.startswith("google")}
    for key in list(saved.keys()):
        sys.modules.pop(key)

    mod = _load_config_fresh()
    mod._load_secret("JWT_SECRET", "JWT_SECRET", sm_enabled=False)

    # Verify SDK was never imported
    assert "google.cloud.secretmanager" not in sys.modules

    # Restore
    sys.modules.update(saved)


# ---------------------------------------------------------------------------
# C: Cross-check — _load_secret uses os.environ correctly
# ---------------------------------------------------------------------------

def test_load_secret_C_env_over_default(monkeypatch):
    """C: env var takes priority over empty string default when SM disabled."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "env-google-client-id")

    mod = _load_config_fresh()
    result = mod._load_secret("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_ID", sm_enabled=False)

    assert result == "env-google-client-id"


def test_load_secret_C_all_seven_env_fallback(monkeypatch):
    """C: All 7 secret fields resolve from env when SM disabled."""
    from scripts.gcp.secret_manager import SECRET_NAMES

    expected = {name: f"env-value-for-{name}" for name in SECRET_NAMES}
    for name, val in expected.items():
        monkeypatch.setenv(name, val)

    mod = _load_config_fresh()
    for name in SECRET_NAMES:
        result = mod._load_secret(name, name, sm_enabled=False)
        assert result == expected[name], f"Expected {expected[name]} for {name}, got {result}"
