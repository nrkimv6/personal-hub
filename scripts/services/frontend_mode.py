"""Frontend runtime contract helpers."""

from __future__ import annotations

import os
from collections.abc import Mapping

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
