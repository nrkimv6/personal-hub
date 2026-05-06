r"""Frontend E2E shard selection contract.

This module is source evidence for merge-test selection.  The broad
``tests\e2e\frontend`` directory is allowed only as an explicit long-run
diagnostic, never as default merge evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PureWindowsPath


BROAD_FRONTEND_E2E_DIRECTORY = r"tests\e2e\frontend"


@dataclass(frozen=True)
class FrontendE2EShard:
    shard_id: str
    files: tuple[str, ...]
    surfaces: tuple[str, ...]
    preconditions: tuple[str, ...]
    expected_max_seconds: int

    @property
    def command(self) -> str:
        file_args = " ".join(self.files)
        return f'python -m pytest -o addopts="--capture=sys -m e2e" {file_args} -v'


FRONTEND_E2E_SHARDS: tuple[FrontendE2EShard, ...] = (
    FrontendE2EShard(
        shard_id="dev-runner-live-log",
        files=(r"tests\e2e\frontend\test_dev_runner_live_log_fallback_e2e.py",),
        surfaces=("dev-runner", "automation", "admin"),
        preconditions=("admin API", "admin frontend", "Playwright"),
        expected_max_seconds=60,
    ),
    FrontendE2EShard(
        shard_id="dev-runner-managed-live-log",
        files=(r"tests\e2e\frontend\test_dev_runner_managed_live_log_catchup_e2e.py",),
        surfaces=("dev-runner", "automation", "admin"),
        preconditions=("admin API", "admin frontend", "Playwright"),
        expected_max_seconds=90,
    ),
    FrontendE2EShard(
        shard_id="file-search-preview",
        files=(r"tests\e2e\frontend\test_file_search_preview_e2e.py",),
        surfaces=("file-search", "admin"),
        preconditions=("admin API", "admin frontend", "Playwright"),
        expected_max_seconds=180,
    ),
    FrontendE2EShard(
        shard_id="expo-public",
        files=(r"tests\e2e\frontend\test_public_expo_booth_map.py",),
        surfaces=("expo", "public", "admin"),
        preconditions=("admin API", "admin frontend", "public frontend", "Playwright"),
        expected_max_seconds=210,
    ),
    FrontendE2EShard(
        shard_id="navigation-smoke",
        files=(
            r"tests\e2e\frontend\test_navigation.py",
            r"tests\e2e\frontend\test_public_navigation.py",
        ),
        surfaces=("navigation", "admin", "public"),
        preconditions=("admin API", "admin frontend", "public frontend", "Playwright"),
        expected_max_seconds=240,
    ),
    FrontendE2EShard(
        shard_id="tracking",
        files=(
            r"tests\e2e\frontend\test_tracking_tab_e2e.py",
            r"tests\e2e\frontend\test_tracking_tab_plan_link_e2e.py",
        ),
        surfaces=("tracking", "automation", "admin"),
        preconditions=("admin API", "admin frontend", "Playwright"),
        expected_max_seconds=180,
    ),
)


DEFAULT_EVIDENCE_SHARD_IDS = frozenset(
    {
        "dev-runner-live-log",
        "dev-runner-managed-live-log",
        "file-search-preview",
        "expo-public",
        "navigation-smoke",
        "tracking",
    }
)


def default_evidence_shards() -> tuple[FrontendE2EShard, ...]:
    return tuple(shard for shard in FRONTEND_E2E_SHARDS if shard.shard_id in DEFAULT_EVIDENCE_SHARD_IDS)


def default_evidence_commands() -> tuple[str, ...]:
    return tuple(shard.command for shard in default_evidence_shards())


def is_broad_frontend_e2e_command(command: str) -> bool:
    normalized = command.replace("/", "\\").replace("`", " ")
    normalized = " ".join(normalized.split())
    broad = str(PureWindowsPath(BROAD_FRONTEND_E2E_DIRECTORY))
    if broad not in normalized:
        return False

    suffix = normalized.split(broad, 1)[1].lstrip()
    return suffix == "" or suffix.startswith("-")
