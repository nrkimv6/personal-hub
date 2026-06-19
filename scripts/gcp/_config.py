"""GCP provisioning configuration — env-var driven, free-tier constants."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Free-tier upper bounds (hardcoded — inherited from design contracts)
# ---------------------------------------------------------------------------
FREE_TIER = {
    "bigquery_storage_gb": 10,
    "bigquery_query_tb": 1,
    "artifact_registry_gb": 0.5,
    "cloud_build_minutes_per_day": 120,
    "cloud_run_min_instances": 0,
    "bigquery_partition_expiration_days": 730,
}


def _parse_bool(value: str, default: bool = False) -> bool:
    """Parse env-var string to bool; non-boolean strings raise ValueError."""
    if value == "":
        return default
    lower = value.strip().lower()
    if lower in ("1", "true", "yes"):
        return True
    if lower in ("0", "false", "no"):
        return False
    raise ValueError(f"Cannot parse boolean from env value: {value!r}")


@dataclass
class GcpConfig:
    project_id: str
    region: str
    dataset_name: str
    ar_repo_name: str
    cloud_run_service: str
    enable_cloud_build: bool = False
    enable_artifact_registry: bool = False


def load_config() -> GcpConfig:
    """Load GcpConfig from environment variables with safe defaults."""
    project_id = os.environ.get("GCP_PROJECT_ID", "personal-hub-project")
    region = os.environ.get("GCP_REGION", "asia-northeast3")
    dataset_name = os.environ.get("GCP_BQ_DATASET", "personal_hub_events")
    ar_repo_name = os.environ.get("GCP_AR_REPO", "personal-hub-repo")
    cloud_run_service = os.environ.get("GCP_CLOUD_RUN_SERVICE", "personal-hub")

    raw_cloud_build = os.environ.get("ENABLE_CLOUD_BUILD", "false")
    raw_ar = os.environ.get("ENABLE_ARTIFACT_REGISTRY", "false")

    return GcpConfig(
        project_id=project_id,
        region=region,
        dataset_name=dataset_name,
        ar_repo_name=ar_repo_name,
        cloud_run_service=cloud_run_service,
        enable_cloud_build=_parse_bool(raw_cloud_build, default=False),
        enable_artifact_registry=_parse_bool(raw_ar, default=False),
    )
