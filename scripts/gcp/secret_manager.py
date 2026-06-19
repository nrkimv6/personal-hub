"""GCP Secret Manager provisioning (cost-guard gated).

Provision is disabled by default (ENABLE_SECRET_MANAGER=false).
Set ENABLE_SECRET_MANAGER=true to enable Secret Manager resources.

Note: Actual ``gcloud secrets create`` and version-add execution requires
deploy-owner explicit approval. This module is dry-run safe by default.
"""

from __future__ import annotations

from scripts.gcp._config import GcpConfig
from scripts.gcp._runner import CmdResult, CostGuardBlocked, cost_guard, resource_exists, run_cmd

# ---------------------------------------------------------------------------
# Target secrets (confirmed in todo-1 §1)
# ---------------------------------------------------------------------------
SECRET_NAMES: list[str] = [
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "EMAIL_ADDRESS",
    "EMAIL_PASSWORD",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "JWT_SECRET",
]


def provision_secrets(cfg: GcpConfig, dry_run: bool = True) -> list[CmdResult]:
    """Create Secret Manager secrets (cost-guard gated, idempotent).

    Args:
        cfg: GCP provisioning config. ``cfg.enable_secret_manager`` must be
            ``True``; otherwise :class:`~scripts.gcp._runner.CostGuardBlocked`
            is raised.
        dry_run: When ``True`` (default) only prints commands without executing
            them via subprocess.

    Returns:
        List of :class:`~scripts.gcp._runner.CmdResult` — one entry per secret
        that was (or would be) created. Already-existing secrets are skipped.

    Raises:
        CostGuardBlocked: if ``cfg.enable_secret_manager`` is ``False``.
    """
    cost_guard("ENABLE_SECRET_MANAGER", cfg.enable_secret_manager)

    results: list[CmdResult] = []

    for name in SECRET_NAMES:
        already_exists = not dry_run and resource_exists(
            [
                "gcloud",
                "secrets",
                "describe",
                name,
                "--project",
                cfg.project_id,
            ]
        )

        if already_exists:
            print(f"[skip] Secret {name!r} already exists in {cfg.project_id}")
        else:
            result = run_cmd(
                [
                    "gcloud",
                    "secrets",
                    "create",
                    name,
                    "--replication-policy=automatic",
                    "--project",
                    cfg.project_id,
                ],
                dry_run=dry_run,
            )
            results.append(result)

    return results


def add_secret_version(
    name: str,
    cfg: GcpConfig,
    value_placeholder: str = "PLACEHOLDER",
    dry_run: bool = True,
) -> CmdResult:
    """Add a new version to an existing secret (placeholder value only).

    IMPORTANT: This function only uses ``value_placeholder`` in dry-run mode
    output. The actual secret value must be injected by the deploy owner via
    ``gcloud secrets versions add --data-file=-`` with real credentials piped
    from stdin — never committed to source control.

    Args:
        name: Secret name (must be one of :data:`SECRET_NAMES`).
        cfg: GCP provisioning config.
        value_placeholder: Placeholder string shown in dry-run output; never
            used as real secret material.
        dry_run: When ``True`` (default) only prints commands without executing
            subprocess.

    Returns:
        :class:`~scripts.gcp._runner.CmdResult` for the version-add command.
    """
    # In dry-run the command string includes "--data-file=-" to indicate that
    # the real value is piped via stdin by the deploy owner.
    return run_cmd(
        [
            "gcloud",
            "secrets",
            "versions",
            "add",
            name,
            "--data-file=-",
            "--project",
            cfg.project_id,
        ],
        dry_run=dry_run,
    )
