"""Plan archive file reference extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REPO_PREFIXES = (
    "app/",
    "frontend/",
    "scripts/",
    "tests/",
    "docs/",
    ".agents/",
    ".claude/",
)

PATH_RE = re.compile(
    r"(?P<path>(?:app|frontend|scripts|tests|docs|\.agents|\.claude)/"
    r"[A-Za-z0-9가-힣_./@+\-=]+\.[A-Za-z0-9_+-]+)"
)


@dataclass(frozen=True)
class FileRefInput:
    path: str
    source_type: str = "mentioned_in_plan"
    module: str | None = None
    evidence: str | None = None
    chunk_index: int | None = None
    exists_at_index: bool = False


def normalize_repo_path(value: str) -> str:
    """Normalize a repo-relative path without resolving it to an absolute path."""
    normalized = (value or "").strip().strip("`'\".,;:")
    normalized = normalized.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def module_from_path(path: str) -> str | None:
    parts = normalize_repo_path(path).split("/")
    if not parts or parts[0] not in {p.rstrip("/") for p in REPO_PREFIXES}:
        return None
    if parts[0] in {"app", "frontend", "tests", "docs", "scripts"} and len(parts) > 1:
        return "/".join(parts[:2])
    return parts[0]


def _iter_candidate_lines(raw_content: str) -> Iterable[tuple[int | None, str]]:
    for line in (raw_content or "").splitlines():
        yield None, line


def extract_file_refs(raw_content: str, repo_root: str | Path | None = None) -> list[FileRefInput]:
    """Extract repo-relative file mentions from markdown text."""
    root = Path(repo_root) if repo_root else None
    refs: dict[str, FileRefInput] = {}
    for chunk_index, line in _iter_candidate_lines(raw_content):
        for match in PATH_RE.finditer(line):
            path = normalize_repo_path(match.group("path"))
            if not path.startswith(REPO_PREFIXES):
                continue
            exists = bool(root and (root / path).exists())
            refs[path] = FileRefInput(
                path=path,
                module=module_from_path(path),
                evidence=line.strip()[:500] or None,
                chunk_index=chunk_index,
                exists_at_index=exists,
            )
    return sorted(refs.values(), key=lambda item: item.path)
