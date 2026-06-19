"""TC: _config.py — RIGHT-BICEP coverage."""

import os
import pytest

from scripts.gcp._config import GcpConfig, _parse_bool, load_config


def test_load_config_R_defaults(monkeypatch):
    """R: no env-vars → default GcpConfig values."""
    for key in (
        "GCP_PROJECT_ID", "GCP_REGION", "GCP_BQ_DATASET",
        "GCP_AR_REPO", "GCP_CLOUD_RUN_SERVICE",
        "ENABLE_CLOUD_BUILD", "ENABLE_ARTIFACT_REGISTRY",
    ):
        monkeypatch.delenv(key, raising=False)

    cfg = load_config()
    assert isinstance(cfg, GcpConfig)
    assert cfg.project_id == "personal-hub-project"
    assert cfg.region == "asia-northeast3"
    assert cfg.dataset_name == "personal_hub_events"
    assert cfg.ar_repo_name == "personal-hub-repo"
    assert cfg.cloud_run_service == "personal-hub"
    assert cfg.enable_cloud_build is False
    assert cfg.enable_artifact_registry is False


def test_load_config_B_empty_env(monkeypatch):
    """B: empty string env-vars → defaults (not crash)."""
    monkeypatch.setenv("ENABLE_CLOUD_BUILD", "")
    monkeypatch.setenv("ENABLE_ARTIFACT_REGISTRY", "")
    cfg = load_config()
    assert cfg.enable_cloud_build is False
    assert cfg.enable_artifact_registry is False


def test_load_config_E_invalid_flag(monkeypatch):
    """E: non-boolean string for ENABLE flag → ValueError."""
    monkeypatch.setenv("ENABLE_CLOUD_BUILD", "maybe")
    with pytest.raises(ValueError, match="Cannot parse boolean"):
        load_config()


def test_parse_bool_truthy_values():
    for v in ("1", "true", "True", "TRUE", "yes", "YES"):
        assert _parse_bool(v) is True


def test_parse_bool_falsy_values():
    for v in ("0", "false", "False", "FALSE", "no", "NO"):
        assert _parse_bool(v) is False
