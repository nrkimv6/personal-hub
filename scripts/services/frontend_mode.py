"""Frontend runtime contract helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

MONITOR_FRONTEND_MODE_ENV = "MONITOR_FRONTEND_MODE"
MONITOR_SVELTEKIT_OUTDIR_ENV = "MONITOR_SVELTEKIT_OUTDIR"

ADMIN_FRONTEND_MODE = "admin"
PUBLIC_FRONTEND_MODE = "public"

ADMIN_FRONTEND_OUTDIR = ".svelte-kit-admin"
PUBLIC_FRONTEND_OUTDIR = ".svelte-kit-public"
DEFAULT_FRONTEND_OUTDIR = ".svelte-kit"


def get_frontend_mode(public: bool) -> str:
    return PUBLIC_FRONTEND_MODE if public else ADMIN_FRONTEND_MODE


def get_frontend_outdir(public: bool) -> str:
    return PUBLIC_FRONTEND_OUTDIR if public else ADMIN_FRONTEND_OUTDIR


def build_frontend_env(
    base_env: Mapping[str, str] | None = None,
    *,
    public: bool,
    api_port: int | None = None,
) -> dict[str, str]:
    env = dict(base_env or os.environ)
    env[MONITOR_FRONTEND_MODE_ENV] = get_frontend_mode(public)
    env[MONITOR_SVELTEKIT_OUTDIR_ENV] = get_frontend_outdir(public)
    if api_port is None:
        env.pop("VITE_API_PORT", None)
    else:
        env["VITE_API_PORT"] = str(api_port)
    return env


def describe_frontend_runtime(public: bool) -> str:
    return f"mode={get_frontend_mode(public)} outDir={get_frontend_outdir(public)}"


def build_frontend_build_log_path(log_dir: Path, timestamp: str, public: bool) -> Path:
    mode = "public" if public else "admin"
    return log_dir / f"frontend_build_{mode}_{timestamp}.log"


def _normalize_frontend_build_output(output: str) -> str:
    normalized = output.rstrip("\r\n")
    return normalized if normalized.strip() else "(no output)"


def render_frontend_build_log(
    mode: str,
    outdir: str,
    returncode: int,
    stdout: str,
    stderr: str,
) -> str:
    stdout_block = _normalize_frontend_build_output(stdout)
    stderr_block = _normalize_frontend_build_output(stderr)
    return (
        "frontend build failure\n"
        f"mode={mode}\n"
        f"outDir={outdir}\n"
        f"returncode={returncode}\n"
        "\n[stdout]\n"
        f"{stdout_block}\n"
        "\n[stderr]\n"
        f"{stderr_block}\n"
    )


def write_frontend_build_log(
    log_dir: Path,
    timestamp: str,
    *,
    public: bool,
    returncode: int,
    stdout: str,
    stderr: str,
) -> Path:
    log_path = build_frontend_build_log_path(log_dir, timestamp, public)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        render_frontend_build_log(
            mode=get_frontend_mode(public),
            outdir=get_frontend_outdir(public),
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        ),
        encoding="utf-8",
    )
    return log_path


def ensure_frontend_runtime_tsconfigs(frontend_dir: Path) -> None:
    """Ensure mode-specific tsconfig copies exist for SvelteKit parsing.

    SvelteKit validates the root tsconfig before generating the mode-specific
    outDir config, so both runtime locations need a materialized tsconfig file.
    """

    base_tsconfig = frontend_dir / DEFAULT_FRONTEND_OUTDIR / "tsconfig.json"
    if not base_tsconfig.exists():
        subprocess.run(
            ["npm.cmd", "run", "prepare"],
            cwd=str(frontend_dir),
            check=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )

    if not base_tsconfig.exists():
        return

    for outdir in (ADMIN_FRONTEND_OUTDIR, PUBLIC_FRONTEND_OUTDIR):
        target_dir = frontend_dir / outdir
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(base_tsconfig, target_dir / "tsconfig.json")
