"""TC: bigquery.py — command-builder validation (subprocess mocked)."""

from unittest.mock import patch

from scripts.gcp._config import GcpConfig
from scripts.gcp.bigquery import provision_bigquery


def _make_cfg() -> GcpConfig:
    return GcpConfig(
        project_id="test-project",
        region="asia-northeast3",
        dataset_name="personal_hub_events",
        ar_repo_name="test-repo",
        cloud_run_service="test-service",
    )


def test_provision_bigquery_R_table_args():
    """R: bq mk command includes 7 columns, partition, cluster, require_partition_filter."""
    cfg = _make_cfg()
    results = provision_bigquery(cfg, dry_run=True)

    # collect all stdout strings
    all_stdout = " ".join(r.stdout for r in results)

    # 7 columns present
    for col in ("event_time", "event_type", "module", "status", "duration_ms", "severity", "error_type"):
        assert col in all_stdout, f"column {col!r} missing from bq mk command"

    # partition + cluster + require_partition_filter
    assert "partition" in all_stdout.lower()
    assert "cluster" in all_stdout.lower() or "clustering" in all_stdout.lower()
    assert "require_partition_filter" in all_stdout
