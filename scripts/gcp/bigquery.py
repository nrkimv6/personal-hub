"""BigQuery dataset/table provisioning for personal_hub_events.

Note: Looker Studio dashboard creation and publish are NOT automated here.
This module only provisions the dataset/table as a Looker data source.
Dashboard creation remains a manual step (out of scope for CLI provisioning).
"""

from __future__ import annotations

from scripts.gcp._config import FREE_TIER, GcpConfig
from scripts.gcp._runner import CmdResult, resource_exists, run_cmd

# personal_hub_events table schema (7 columns from bigquery-schema-design.md)
_SCHEMA = (
    "event_time:TIMESTAMP,"
    "event_type:STRING,"
    "module:STRING,"
    "status:STRING,"
    "duration_ms:INTEGER,"
    "severity:STRING,"
    "error_type:STRING"
)

_TIME_PARTITIONING = "type=DAY,field=event_time"
_CLUSTERING_FIELDS = "module,event_type"


def provision_bigquery(cfg: GcpConfig, dry_run: bool = True) -> list[CmdResult]:
    """Provision BigQuery dataset and personal_hub_events table (idempotent)."""
    results: list[CmdResult] = []

    dataset_ref = f"{cfg.project_id}:{cfg.dataset_name}"
    table_ref = f"{cfg.project_id}:{cfg.dataset_name}.personal_hub_events"

    # --- dataset ---
    dataset_exists = not dry_run and resource_exists(
        ["bq", "show", "--dataset", dataset_ref]
    )
    if dataset_exists:
        print(f"[skip] dataset {dataset_ref} already exists")
    else:
        expiration_ms = FREE_TIER["bigquery_partition_expiration_days"] * 24 * 3600 * 1000
        result = run_cmd(
            [
                "bq",
                "mk",
                "--dataset",
                f"--default_partition_expiration={expiration_ms}",
                dataset_ref,
            ],
            dry_run=dry_run,
        )
        results.append(result)

    # --- table ---
    table_exists = not dry_run and resource_exists(["bq", "show", table_ref])
    if table_exists:
        print(f"[skip] table {table_ref} already exists")
    else:
        result = run_cmd(
            [
                "bq",
                "mk",
                "--table",
                f"--schema={_SCHEMA}",
                f"--time_partitioning_type=DAY",
                f"--time_partitioning_field=event_time",
                f"--time_partitioning_expiration={FREE_TIER['bigquery_partition_expiration_days'] * 86400 * 1000}",
                f"--clustering_fields={_CLUSTERING_FIELDS}",
                f"--require_partition_filter=true",
                table_ref,
            ],
            dry_run=dry_run,
        )
        results.append(result)

    return results
