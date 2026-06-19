"""TC: cloud_build.py — cost-guard gate validation (dry-run)."""

import pytest

from scripts.gcp._config import GcpConfig
from scripts.gcp._runner import CostGuardBlocked
from scripts.gcp.cloud_build import provision_artifact_registry, provision_cloud_build


def _make_cfg(enable_ar: bool = False, enable_cb: bool = False) -> GcpConfig:
    return GcpConfig(
        project_id="test-project",
        region="asia-northeast3",
        dataset_name="personal_hub_events",
        ar_repo_name="test-repo",
        cloud_run_service="test-service",
        enable_artifact_registry=enable_ar,
        enable_cloud_build=enable_cb,
    )


def test_provision_artifact_registry_E_blocked_when_disabled():
    """E: ENABLE_ARTIFACT_REGISTRY=false → CostGuardBlocked."""
    cfg = _make_cfg(enable_ar=False)
    with pytest.raises(CostGuardBlocked) as exc_info:
        provision_artifact_registry(cfg, dry_run=True)
    assert "ENABLE_ARTIFACT_REGISTRY" in str(exc_info.value)


def test_provision_cloud_build_E_blocked_when_disabled():
    """E: ENABLE_CLOUD_BUILD=false → CostGuardBlocked."""
    cfg = _make_cfg(enable_cb=False)
    with pytest.raises(CostGuardBlocked) as exc_info:
        provision_cloud_build(cfg, dry_run=True)
    assert "ENABLE_CLOUD_BUILD" in str(exc_info.value)


def test_provision_artifact_registry_R_enabled_dry_run():
    """R: ENABLE_ARTIFACT_REGISTRY=true + dry_run → commands printed, no real calls."""
    cfg = _make_cfg(enable_ar=True)
    results = provision_artifact_registry(cfg, dry_run=True)
    assert len(results) >= 1
    all_stdout = " ".join(r.stdout for r in results)
    assert "artifacts" in all_stdout or "gcloud" in all_stdout


def test_provision_cloud_build_R_enabled_dry_run():
    """R: ENABLE_CLOUD_BUILD=true + dry_run → commands printed, no real calls."""
    cfg = _make_cfg(enable_cb=True)
    results = provision_cloud_build(cfg, dry_run=True)
    assert len(results) >= 1
    assert results[0].dry_run is True
