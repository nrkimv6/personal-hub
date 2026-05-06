"""Repository registry for Plan Archive cross-repo indexing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from app.core.config import PROJECT_ROOT
from app.modules.dev_runner.config import config


@dataclass(frozen=True)
class RepoRegistryEntry:
    repo_key: str
    repo_root: Path
    source: str
    status: str = "ready"
    reason: str | None = None


def normalize_repo_key(name: str | None, repo_root: Path) -> str:
    """Return a stable, UI-safe repo key for a project root."""
    raw = (name or repo_root.name or str(repo_root)).strip().lower()
    safe = "".join(ch if ch.isalnum() else "-" for ch in raw)
    while "--" in safe:
        safe = safe.replace("--", "-")
    return safe.strip("-") or "unknown"


class PlanArchiveRepoRegistry:
    """Load repo roots that may contribute git evidence for archived plans."""

    def __init__(
        self,
        project_root: Path | None = None,
        wtools_base_dir: Path | None = None,
        project_config_paths: Iterable[Path] | None = None,
    ):
        self.project_root = Path(project_root or PROJECT_ROOT)
        self.wtools_base_dir = Path(wtools_base_dir or config.WTOOLS_BASE_DIR)
        self.project_config_paths = list(project_config_paths or self._default_project_config_paths())

    def list_repos(self) -> list[RepoRegistryEntry]:
        entries: list[RepoRegistryEntry] = []
        seen: set[str] = set()

        self._append_entry(entries, seen, "monitor-page", self.project_root, "project_root")
        plans_root = self.project_root / ".worktrees" / "plans"
        self._append_entry(entries, seen, "monitor-page-plans", plans_root, "plans_worktree")
        self._append_entry(entries, seen, "wtools", self.wtools_base_dir, "wtools_base")

        for name, root in self._load_project_config_entries():
            self._append_entry(entries, seen, name, root, "projects_json")

        return entries

    def _default_project_config_paths(self) -> list[Path]:
        return [
            self.wtools_base_dir / ".agents" / "projects.json",
            self.wtools_base_dir / ".claude" / "projects.json",
        ]

    def _load_project_config_entries(self) -> list[tuple[str | None, Path]]:
        for path in self.project_config_paths:
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            result: list[tuple[str | None, Path]] = []
            for item in data.get("projects", []):
                root = item.get("path") if isinstance(item, dict) else None
                if not root:
                    continue
                result.append((item.get("name"), Path(root)))
            return result
        return []

    def _append_entry(
        self,
        entries: list[RepoRegistryEntry],
        seen: set[str],
        name: str | None,
        repo_root: Path,
        source: str,
    ) -> None:
        try:
            resolved = repo_root.resolve()
        except Exception:
            resolved = repo_root
        key = str(resolved).lower()
        if key in seen:
            return
        seen.add(key)
        status = "ready"
        reason = None
        if not resolved.exists():
            status = "skipped"
            reason = "repo root does not exist"
        elif not (resolved / ".git").exists():
            status = "skipped"
            reason = "not a git repository"
        entries.append(
            RepoRegistryEntry(
                repo_key=normalize_repo_key(name, resolved),
                repo_root=resolved,
                source=source,
                status=status,
                reason=reason,
            )
        )
