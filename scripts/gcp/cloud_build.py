"""Cloud Build + Artifact Registry provisioning (cost-guard gated).

Both resources are disabled by default (ENABLE_CLOUD_BUILD=false,
ENABLE_ARTIFACT_REGISTRY=false).  Set the env-vars to "true" to enable.
"""

from __future__ import annotations

from scripts.gcp._config import GcpConfig
from scripts.gcp._runner import CmdResult, cost_guard, resource_exists, run_cmd


def provision_artifact_registry(cfg: GcpConfig, dry_run: bool = True) -> list[CmdResult]:
    """Create Artifact Registry repo with cleanup policy (cost-guard gated)."""
    cost_guard("ENABLE_ARTIFACT_REGISTRY", cfg.enable_artifact_registry)

    results: list[CmdResult] = []

    repo_exists = not dry_run and resource_exists(
        [
            "gcloud",
            "artifacts",
            "repositories",
            "describe",
            cfg.ar_repo_name,
            "--location", cfg.region,
            "--project", cfg.project_id,
        ]
    )

    if repo_exists:
        print(f"[skip] Artifact Registry repo {cfg.ar_repo_name} already exists")
    else:
        result = run_cmd(
            [
                "gcloud",
                "artifacts",
                "repositories",
                "create",
                cfg.ar_repo_name,
                "--repository-format=docker",
                "--location", cfg.region,
                "--project", cfg.project_id,
                "--description=personal-hub container images",
            ],
            dry_run=dry_run,
        )
        results.append(result)

    # Cleanup policy: 30-day retention, keep at most 10 images
    policy_result = run_cmd(
        [
            "gcloud",
            "artifacts",
            "repositories",
            "set-cleanup-policies",
            cfg.ar_repo_name,
            "--location", cfg.region,
            "--project", cfg.project_id,
            "--policy=keep-minimum-versions",
            "--keep-count=10",
            "--keep-since=30d",
        ],
        dry_run=dry_run,
    )
    results.append(policy_result)

    return results


def provision_cloud_build(cfg: GcpConfig, dry_run: bool = True) -> list[CmdResult]:
    """Create Cloud Build trigger referencing cloudbuild.yaml (cost-guard gated)."""
    cost_guard("ENABLE_CLOUD_BUILD", cfg.enable_cloud_build)

    result = run_cmd(
        [
            "gcloud",
            "builds",
            "triggers",
            "create",
            "github",
            f"--name=personal-hub-build-{cfg.cloud_run_service}",
            "--build-config=cloudbuild.yaml",
            "--project", cfg.project_id,
            "--region", cfg.region,
            "--substitutions",
            f"_ENABLE_CLOUD_BUILD=false,_ENABLE_ARTIFACT_REGISTRY=false",
        ],
        dry_run=dry_run,
    )
    return [result]
