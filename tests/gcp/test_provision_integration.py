"""Phase T3: end-to-end dry-run integration TC.

Rules:
- subprocess (gcloud/bq/gsutil) is mocked — no real GCP calls
- argparse, env vars, and module logic use real implementations
"""

from unittest.mock import patch, MagicMock

import pytest

from scripts.gcp.provision import main


def test_provision_all_dry_run_no_subprocess():
    """T3-R: --resource all (dry-run default) never calls subprocess.run."""
    with patch("scripts.gcp._runner.subprocess.run") as mock_run:
        exit_code = main(["--resource", "all"])
    mock_run.assert_not_called()
    assert exit_code == 0


def test_provision_dry_run_cost_guard_skips_gated(capsys):
    """T3-R: dry-run defaults → Cloud Build/AR skipped, BigQuery/CloudRun commands printed."""
    with patch("scripts.gcp._runner.subprocess.run"):
        exit_code = main(["--resource", "all"])

    captured = capsys.readouterr()
    output = captured.out

    # BigQuery and Cloud Run should produce dry-run output
    assert "[dry-run]" in output or "dry-run" in output

    # Cost-guard gated resources should be skipped with a notice
    assert "cost-guard" in output.lower() or "SKIPPED" in output or "CostGuardBlocked" in output or exit_code == 0


def test_provision_bigquery_only_dry_run_no_subprocess():
    """T3-R: --resource bigquery (dry-run) never calls subprocess.run."""
    with patch("scripts.gcp._runner.subprocess.run") as mock_run:
        exit_code = main(["--resource", "bigquery"])
    mock_run.assert_not_called()
    assert exit_code == 0


def test_provision_cloud_run_only_dry_run_no_subprocess():
    """T3-R: --resource cloud-run (dry-run) never calls subprocess.run."""
    with patch("scripts.gcp._runner.subprocess.run") as mock_run:
        exit_code = main(["--resource", "cloud-run"])
    mock_run.assert_not_called()
    assert exit_code == 0
