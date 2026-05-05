"""plan 경로 후보 계산 및 wtools 프로젝트 루트 로더 — plan_service/plan_path_registry 공유 헬퍼

이 모듈에 함수를 추가할 때 순환 import에 주의한다.
현재 허용 import 체인: plan_path_helpers → config, schemas (pydantic only)
plan_service / plan_scanner / plan_path_registry → plan_path_helpers (역방향 금지)
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Tuple

from app.modules.dev_runner.config import config

logger = logging.getLogger(__name__)


@dataclass
class PlanStorageRootCandidate:
    """등록된 plan/archive 경로에서 유도한 plans lineage worktree 후보."""

    project: str
    repo_root: Path
    worktree_path: Path
    registered_paths: list[str] = field(default_factory=list)


def _dedupe_paths(paths: List[Path]) -> List[Path]:
    deduped: List[Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            resolved = str(path.resolve())
        except Exception:
            resolved = str(path)
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(path)
    return deduped


def canonicalize_wtools_legacy_common_path(path_str: str, path_type: str) -> Optional[tuple[str, str]]:
    """wtools legacy common/docs/{plan|archive} 등록 경로를 canonical plans worktree로 치환한다."""
    try:
        resolved = Path(path_str).resolve()
        base = config.WTOOLS_BASE_DIR.resolve()
        legacy = base / "common" / "docs" / path_type
        canonical = base / ".worktrees" / "plans" / "docs" / path_type
        if resolved == legacy:
            return str(canonical.resolve()), path_type
    except Exception:
        return None
    return None


def load_wtools_project_roots() -> List[Path]:
    """wtools .claude/projects.json에서 프로젝트 루트 목록을 반환한다.

    파일이 없거나 읽기 실패 시 빈 목록을 반환 (호출처에서 fallback 처리).
    Format: {"projects": [{"name": "...", "path": "C:\\...", ...}, ...]}
    """
    projects_json = config.WTOOLS_BASE_DIR / ".claude" / "projects.json"
    if not projects_json.exists():
        return []
    try:
        data = json.loads(projects_json.read_text(encoding="utf-8"))
        projects = data.get("projects", [])
        roots: List[Path] = []
        if config.WTOOLS_BASE_DIR.is_absolute():
            roots.append(config.WTOOLS_BASE_DIR)
        for proj in projects:
            path_str = proj.get("path")
            if path_str:
                p = Path(path_str)
                if p.is_absolute():
                    roots.append(p)
        roots = _dedupe_paths(roots)
        logger.debug(f"[projects.json] {len(roots)}개 프로젝트 루트 로드")
        return roots
    except Exception as e:
        logger.warning(f"[projects.json] 로드 실패: {e}")
        return []


def iter_repo_plan_path_candidates(repo_root: Path) -> List[Tuple[Path, str]]:
    """repo 루트에서 docs/* 및 .worktrees/plans/docs/* 경로 후보를 반환한다.

    반환: [(path, path_type), ...] — path_type은 "plan" 또는 "archive"
    존재 여부와 무관하게 4개 후보를 모두 반환한다. 존재 확인은 호출처에서 수행.
    """
    return [
        (repo_root / ".worktrees" / "plans" / "docs" / "plan", "plan"),
        (repo_root / ".worktrees" / "plans" / "docs" / "archive", "archive"),
        (repo_root / "docs" / "plan", "plan"),
        (repo_root / "docs" / "archive", "archive"),
    ]


def _read_registered_path(item: Any) -> str | None:
    if isinstance(item, dict):
        value = item.get("path")
    else:
        value = getattr(item, "path", None)
    return value if isinstance(value, str) and value else None


def _project_label_from_repo_root(repo_root: Path) -> str:
    name = repo_root.name.strip()
    return name or str(repo_root)


def collect_plan_storage_root_candidates(registered_paths: List[Any]) -> list[PlanStorageRootCandidate]:
    """등록된 plan/archive 경로에서 repo별 `.worktrees/plans` 후보를 중복 없이 반환한다."""
    candidates: list[PlanStorageRootCandidate] = []
    by_root: dict[str, PlanStorageRootCandidate] = {}

    for item in registered_paths:
        raw_path = _read_registered_path(item)
        if not raw_path:
            continue
        repo_root_str = extract_repo_root_from_plan_path(raw_path)
        if not repo_root_str:
            continue
        repo_root = Path(repo_root_str)
        try:
            key = str(repo_root.resolve()).lower()
        except Exception:
            key = str(repo_root).lower()
        candidate = by_root.get(key)
        if candidate is None:
            candidate = PlanStorageRootCandidate(
                project=_project_label_from_repo_root(repo_root),
                repo_root=repo_root,
                worktree_path=repo_root / ".worktrees" / "plans",
            )
            by_root[key] = candidate
            candidates.append(candidate)
        if raw_path not in candidate.registered_paths:
            candidate.registered_paths.append(raw_path)

    return candidates


def backfill_dual_paths(entries: List[dict]) -> tuple:
    """기존 등록 목록에서 docs <-> worktree 상호 보완 경로를 backfill한다.

    docs/plan 만 등록되어 있고 .worktrees/plans/docs/plan 이 실재하면 추가 (vice versa).

    동작:
    - entries 각 항목의 repo_root를 추출
    - iter_repo_plan_path_candidates()로 4개 후보 경로를 얻음
    - 같은 타입(plan/archive)의 누락 경로가 실재(exists())하면 추가
    - 이미 존재하는 경로(path 문자열 + type 키)는 중복 추가하지 않음 (no-op)

    반환: (entries_with_additions: List[dict], changed: bool)
    """
    existing_keys: set = {
        (e["path"], e.get("type", "plan")) for e in entries
    }
    additions: List[dict] = []

    for entry in entries:
        raw_path = entry.get("path", "")
        path_type = entry.get("type", "plan")
        repo_root_str = extract_repo_root_from_plan_path(raw_path)
        if not repo_root_str:
            continue
        repo_root = Path(repo_root_str)
        for candidate_path, cand_type in iter_repo_plan_path_candidates(repo_root):
            if cand_type != path_type:
                continue
            resolved = str(candidate_path.resolve())
            key = (resolved, cand_type)
            if key not in existing_keys and candidate_path.exists():
                additions.append({"path": resolved, "type": cand_type})
                existing_keys.add(key)

    if additions:
        return entries + additions, True
    return entries, False


def dedupe_prefer_worktree(results: List) -> List:
    """같은 (repo_root, filename)이면 worktree 경로를 남기고 docs 경로를 제거한다.

    인자: PlanFileResponse 목록 (path, filename 속성 필요)
    반환: 중복 제거된 PlanFileResponse 목록

    규칙:
    - repo_root가 추출되지 않는 항목은 그대로 유지 (ungrouped)
    - 같은 (repo_root, filename) 그룹 내에서 .worktrees 포함 경로 우선 선택
    - worktree 경로가 없으면 그룹 첫 번째 항목 선택
    """
    groups: dict = {}
    ungrouped: List = []

    for item in results:
        repo_root = extract_repo_root_from_plan_path(item.path)
        if repo_root:
            key = (repo_root, item.filename)
            groups.setdefault(key, []).append(item)
        else:
            ungrouped.append(item)

    deduped: List = list(ungrouped)
    for group in groups.values():
        if len(group) == 1:
            deduped.append(group[0])
            continue
        worktree_items = [g for g in group if ".worktrees" in Path(g.path).parts]
        deduped.append(worktree_items[0] if worktree_items else group[0])

    return deduped


def extract_repo_root_from_plan_path(path_str: str) -> Optional[str]:
    """등록된 경로 문자열에서 논리적 repo 루트를 추출한다.

    - `{repo}/.worktrees/plans/docs/{plan|archive}` → `{repo}`
    - `{repo}/docs/{plan|archive}` → `{repo}`
    반환 실패 시 None.
    """
    try:
        p = Path(path_str)
        resolved = p.resolve()
        wtools_root = config.WTOOLS_BASE_DIR.resolve()
        for path_type in ("plan", "archive"):
            legacy_common_root = wtools_root / "common" / "docs" / path_type
            if resolved == legacy_common_root or legacy_common_root in resolved.parents:
                return str(wtools_root)
        parts = list(p.parts)
        # .worktrees/plans/docs 패턴 탐지
        for i, part in enumerate(parts):
            if (part == ".worktrees" and i + 3 < len(parts)
                    and parts[i + 1] == "plans" and parts[i + 2] == "docs"):
                if i > 0:
                    return str(Path(*parts[:i]))
                return None
        # docs/{plan|archive} 패턴 탐지
        for i, part in enumerate(parts):
            if part == "docs" and i + 1 < len(parts) and parts[i + 1] in ("plan", "archive"):
                if i > 0:
                    return str(Path(*parts[:i]))
                return None
    except Exception:
        pass
    return None
