"""Cloud Run deployment provisioning.

Uses Dockerfile.cloudrun and inherits cloud-run-poc-design-contract values:
- min-instances: 0 (free-tier: no idle charge)
- concurrency: 80
- port: 8080
"""

from __future__ import annotations

from scripts.gcp._config import GcpConfig
from scripts.gcp._runner import CmdResult, run_cmd


def provision_cloud_run(cfg: GcpConfig, dry_run: bool = True) -> list[CmdResult]:
    """Deploy Cloud Run service (idempotent — redeploy is safe)."""
    results: list[CmdResult] = []

    result = run_cmd(
        [
            "gcloud",
            "run",
            "deploy",
            cfg.cloud_run_service,
            "--source", ".",
            "--region", cfg.region,
            "--port", "8080",
            "--min-instances", "0",
            "--concurrency", "80",
            "--allow-unauthenticated",
            "--project", cfg.project_id,
        ],
        dry_run=dry_run,
    )
    results.append(result)

    # URL read-back command — for deploy owner / todo-16 live verification
    url_readback = run_cmd(
        [
            "gcloud",
            "run",
            "services",
            "describe",
            cfg.cloud_run_service,
            "--region", cfg.region,
            "--project", cfg.project_id,
            "--format=value(status.url)",
        ],
        dry_run=dry_run,
    )
    results.append(url_readback)

    return results
