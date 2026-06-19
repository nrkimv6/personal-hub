"""Command runner with dry-run, idempotency helpers, and cost-guard gate."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


class CostGuardBlocked(Exception):
    """Raised when a cost-guard flag is false and blocks provisioning."""

    def __init__(self, flag_name: str) -> None:
        super().__init__(
            f"Cost-guard blocked: {flag_name}=false. "
            f"Set {flag_name}=true to enable this resource."
        )
        self.flag_name = flag_name


@dataclass
class CmdResult:
    returncode: int
    stdout: str
    stderr: str
    cmd: list
    dry_run: bool


def run_cmd(args: list, dry_run: bool = True) -> CmdResult:
    """Run a gcloud/bq/gsutil command. In dry-run mode, print only."""
    if dry_run:
        preview = " ".join(str(a) for a in args)
        print(f"[dry-run] {preview}")
        return CmdResult(
            returncode=0,
            stdout=f"[dry-run] {preview}",
            stderr="",
            cmd=list(args),
            dry_run=True,
        )

    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
    )
    return CmdResult(
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        cmd=list(args),
        dry_run=False,
    )


def resource_exists(describe_args: list) -> bool:
    """Check if a GCP resource exists by running a describe/list command."""
    result = subprocess.run(
        describe_args,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def cost_guard(flag_name: str, enabled: bool) -> None:
    """Raise CostGuardBlocked if the cost-guard flag is false."""
    if not enabled:
        raise CostGuardBlocked(flag_name)
