"""GCP provisioning CLI — idempotent dry-run by default.

Usage:
    python scripts/gcp/provision.py --resource all
    python scripts/gcp/provision.py --resource bigquery --apply
    python scripts/gcp/provision.py --resource cloud-run --project my-proj
"""

from __future__ import annotations

import argparse
import sys

from scripts.gcp._config import load_config
from scripts.gcp._runner import CostGuardBlocked
from scripts.gcp.bigquery import provision_bigquery
from scripts.gcp.cloud_build import provision_artifact_registry, provision_cloud_build
from scripts.gcp.cloud_run import provision_cloud_run
from scripts.gcp.secret_manager import provision_secrets


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="GCP provisioning CLI (dry-run by default)"
    )
    parser.add_argument(
        "--resource",
        choices=["cloud-run", "bigquery", "cloud-build", "secret-manager", "all"],
        default="all",
        help="Resource to provision",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Actually execute commands (default: dry-run only)",
    )
    parser.add_argument("--project", default=None, help="GCP project id override")
    parser.add_argument("--region", default=None, help="GCP region override")
    return parser


def main(argv: list | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    cfg = load_config()
    if args.project:
        cfg.project_id = args.project
    if args.region:
        cfg.region = args.region

    dry_run = not args.apply

    if dry_run:
        print("[dry-run] No real GCP resources will be created.")
        print(f"[dry-run] project={cfg.project_id} region={cfg.region}")

    resources = (
        ["bigquery", "cloud-run", "cloud-build"]
        if args.resource == "all"
        else [args.resource]
    )

    exit_code = 0
    for resource in resources:
        try:
            if resource == "bigquery":
                provision_bigquery(cfg, dry_run=dry_run)
            elif resource == "cloud-run":
                provision_cloud_run(cfg, dry_run=dry_run)
            elif resource == "cloud-build":
                provision_artifact_registry(cfg, dry_run=dry_run)
                provision_cloud_build(cfg, dry_run=dry_run)
            elif resource == "secret-manager":
                provision_secrets(cfg, dry_run=dry_run)
        except CostGuardBlocked as exc:
            print(f"[cost-guard] SKIPPED {resource}: {exc}")
        except Exception as exc:  # noqa: BLE001
            print(f"[error] {resource}: {exc}", file=sys.stderr)
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
