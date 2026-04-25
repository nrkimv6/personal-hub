"""plan 경로 후보 계산 및 wtools 프로젝트 루트 로더 — plan_service/plan_path_registry 공유 헬퍼"""

import json
import logging
from pathlib import Path
from typing import List, Optional, Tuple

from app.modules.dev_runner.config import config

logger = logging.getLogger(__name__)


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
        for proj in projects:
            path_str = proj.get("path")
            if path_str:
                p = Path(path_str)
                if p.is_absolute():
                    roots.append(p)
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
        (repo_root / "docs" / "plan", "plan"),
        (repo_root / "docs" / "archive", "archive"),
        (repo_root / ".worktrees" / "plans" / "docs" / "plan", "plan"),
        (repo_root / ".worktrees" / "plans" / "docs" / "archive", "archive"),
    ]


def extract_repo_root_from_plan_path(path_str: str) -> Optional[str]:
    """등록된 경로 문자열에서 논리적 repo 루트를 추출한다.

    - `{repo}/.worktrees/plans/docs/{plan|archive}` → `{repo}`
    - `{repo}/docs/{plan|archive}` → `{repo}`
    반환 실패 시 None.
    """
    try:
        p = Path(path_str)
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
