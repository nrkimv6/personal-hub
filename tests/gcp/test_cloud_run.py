"""TC: cloud_run.py — command-builder validation (dry-run)."""

from scripts.gcp._config import GcpConfig
from scripts.gcp.cloud_run import provision_cloud_run


def _make_cfg() -> GcpConfig:
    return GcpConfig(
        project_id="test-project",
        region="asia-northeast3",
        dataset_name="personal_hub_events",
        ar_repo_name="test-repo",
        cloud_run_service="test-service",
    )


def test_provision_cloud_run_R_deploy_args():
    """R: gcloud run deploy includes --min-instances 0, --port 8080, region."""
    cfg = _make_cfg()
    results = provision_cloud_run(cfg, dry_run=True)

    all_stdout = " ".join(r.stdout for r in results)

    assert "--min-instances" in all_stdout
    assert "0" in all_stdout
    assert "--port" in all_stdout
    assert "8080" in all_stdout
    assert cfg.region in all_stdout
