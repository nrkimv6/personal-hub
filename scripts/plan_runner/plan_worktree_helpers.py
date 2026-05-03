"""
plan 파일 헤더에서 워크트리 정보를 읽고 쓰는 헬퍼 함수 모음.

dev-runner-command-listener.py 및 테스트에서 공유 사용.
"""

import sys as _sys_inject
from pathlib import Path as _Path_inject
_sys_inject.path.insert(0, str(_Path_inject(__file__).resolve().parent))
del _sys_inject, _Path_inject

import os
import re
import logging
import subprocess
from pathlib import Path
from typing import Optional

from _dr_plan_paths import is_archive_or_history_path

logger = logging.getLogger(__name__)

STALE_MERGE_WARN_BEHIND = 120
STALE_MERGE_BLOCK_BEHIND = 300


def _extract_plan_filename_tail(plan_file: str) -> Optional[Path]:
    """plan 경로 문자열에서 docs/plan 이하 상대 경로를 추출한다.

    common/docs/plan은 active source가 아니라 legacy compatibility 경로이므로
    project plans 워크트리 매핑 후보에서 제외한다.
    """
    normalized = plan_file.replace("\\", "/").strip()
    lower = normalized.lower()
    if "/common/docs/plan/" in lower or lower.startswith("common/docs/plan/"):
        return None

    markers = (
        "/.worktrees/plans/docs/plan/",
        ".worktrees/plans/docs/plan/",
        "/docs/plan/",
        "docs/plan/",
    )
    for marker in markers:
        idx = lower.find(marker.lower())
        if idx < 0:
            continue
        tail = normalized[idx + len(marker):].strip("/")
        if not tail:
            return None
        return Path(*[part for part in tail.split("/") if part])
    return None


def resolve_active_plan_file(plan_file: str, project_root: "Path | None" = None) -> Optional[Path]:
    """활성 plan 파일 경로를 해석한다.

    우선순위:
    1) project_root/.worktrees/plans/docs/plan/{filename_tail} (존재 시 SSOT)
    2) 입력 plan_file의 실제 경로
    """
    if not plan_file:
        return None

    candidates: list[Path] = []
    root = Path(project_root).resolve() if project_root else None
    tail = _extract_plan_filename_tail(plan_file)

    if root and tail:
        plans_ssot = root / ".worktrees" / "plans" / "docs" / "plan" / tail
        candidates.append(plans_ssot)

    path_obj = Path(plan_file)
    if path_obj.is_absolute():
        candidates.insert(1 if candidates else 0, path_obj)
    elif root:
        candidates.insert(1 if candidates else 0, root / path_obj)
    else:
        candidates.insert(0, path_obj)

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()
    return None


def is_worktree_active(plan_file: str, project_root: "Path | None" = None) -> tuple:
    """plan 파일 헤더에서 worktree 경로를 읽고 실제 존재 여부 확인.

    Args:
        plan_file: plan 파일 경로
        project_root: 프로젝트 루트 (None이면 plan_file 위치에서 추론)

    Returns:
        (exists: bool, branch: Optional[str], worktree_abs_path: Optional[str])
    """
    branch, worktree_rel = parse_plan_worktree_info(plan_file)
    if not branch or not worktree_rel:
        return False, None, None

    if project_root is None:
        p = Path(plan_file).resolve()
        parts = list(p.parts)
        if ".worktrees" in parts:
            i = parts.index(".worktrees")
            candidate = Path(*parts[:i])
            project_root = candidate if (candidate / ".git").exists() else p.parent.parent.parent
        else:
            project_root = p.parent.parent.parent

    worktree_abs = (Path(project_root) / worktree_rel).resolve()
    if not worktree_abs.is_dir():
        return False, None, None
    # .git 파일 존재 확인 (git worktree는 .git 파일을 가짐)
    if not (worktree_abs / ".git").exists():
        return False, None, None
    return True, branch, str(worktree_abs)


def is_plan_archived(plan_file: str) -> bool:
    """plan 파일 경로가 docs/archive 또는 docs/history인지 확인"""
    return is_archive_or_history_path(plan_file)


def has_unmerged_commits(branch: str, cwd: "Path | None" = None) -> bool:
    """main 브랜치에 없는 커밋이 branch에 있는지 확인.

    Returns:
        True  → 독자 커밋 있음 (머지 필요)
        False → 독자 커밋 없음 (안전하게 삭제 가능)
    """
    try:
        result = subprocess.run(
            ["git", "log", f"main..{branch}", "--oneline"],
            capture_output=True,
            text=True,
            cwd=str(cwd) if cwd else None,
        )
        return bool(result.stdout.strip())
    except Exception as e:
        logger.warning(f"[has_unmerged_commits] 확인 실패 (보수적으로 True 반환): {e}")
        return True  # 확인 불가 → 안전하게 True


def get_branch_divergence(branch: str, cwd: "Path | None" = None, base: str = "main") -> tuple[Optional[int], Optional[int]]:
    """base...branch 발산도를 계산한다.

    Returns:
        (behind, ahead)
        - behind: base에는 있고 branch에는 없는 커밋 수
        - ahead: branch에는 있고 base에는 없는 커밋 수
        - 실패 시 (None, None). 호출자는 이를 안전하지 않은 상태로 처리해야 한다.
    """
    if not branch or not str(branch).strip():
        return (None, None)
    try:
        result = subprocess.run(
            ["git", "rev-list", "--left-right", "--count", f"{base}...{branch}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(cwd) if cwd else None,
            timeout=15,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip() if isinstance(result.stderr, str) else ""
            logger.warning(
                "[get_branch_divergence] git rev-list 실패 (branch=%s, base=%s, rc=%s): %s",
                branch,
                base,
                result.returncode,
                stderr,
            )
            return (None, None)

        stdout = result.stdout if isinstance(result.stdout, str) else ""
        parts = stdout.strip().split()
        if len(parts) != 2:
            logger.warning(
                "[get_branch_divergence] 출력 파싱 실패 (branch=%s, base=%s, stdout=%r)",
                branch,
                base,
                stdout.strip(),
            )
            return (None, None)
        return (int(parts[0]), int(parts[1]))
    except Exception as e:
        logger.warning(f"[get_branch_divergence] 확인 실패 (보수적으로 BLOCK 대상): {e}")
        return (None, None)


def classify_merge_risk(behind: Optional[int], ahead: Optional[int]) -> str:
    """브랜치 발산도를 PASS/WARN/BLOCK으로 분류한다."""
    if behind is None or ahead is None:
        return "BLOCK"
    if ahead <= 0 or behind <= STALE_MERGE_WARN_BEHIND:
        return "PASS"
    if behind <= STALE_MERGE_BLOCK_BEHIND:
        return "WARN"
    return "BLOCK"


def is_plan_in_progress(plan_file: str) -> bool:
    """plan 파일 상단 20줄에서 '> 상태: 구현중' 패턴 확인"""
    try:
        with open(plan_file, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= 20:
                    break
                if re.match(r"^>\s*상태:\s*구현중", line.strip()):
                    return True
    except Exception:
        pass
    return False


def parse_plan_worktree_info(plan_file: str) -> tuple:
    """plan 파일 상단 20줄에서 '> branch:' / '> worktree:' 추출

    Returns:
        (branch, worktree_rel) — 없으면 None
    """
    branch = None
    worktree_rel = None
    try:
        with open(plan_file, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= 20:
                    break
                m_branch = re.match(r"^>\s*branch:\s*(.+)", line.strip())
                if m_branch:
                    branch = m_branch.group(1).strip()
                m_wt = re.match(r"^>\s*worktree:\s*(.+)", line.strip())
                if m_wt:
                    worktree_rel = m_wt.group(1).strip()
    except Exception:
        pass
    return branch, worktree_rel


def write_plan_worktree_info(plan_file: str, branch: str, worktree_rel: str, owner: str | None = None):
    """plan 파일 헤더에 branch/worktree/worktree-owner를 기록한다."""
    try:
        with open(plan_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        owner_value = str(Path(owner).resolve()) if owner else str(Path(plan_file).resolve())
        branch_line = f"> branch: {branch}\n"
        worktree_line = f"> worktree: {worktree_rel}\n"
        owner_line = f"> worktree-owner: {owner_value}\n"

        # 이미 존재하면 교체
        new_lines = []
        replaced_branch = False
        replaced_worktree = False
        replaced_owner = False
        for line in lines:
            if re.match(r"^>\s*branch:", line):
                new_lines.append(branch_line)
                replaced_branch = True
            elif re.match(r"^>\s*worktree-owner:", line):
                new_lines.append(owner_line)
                replaced_owner = True
            elif re.match(r"^>\s*worktree:", line):
                new_lines.append(worktree_line)
                replaced_worktree = True
            else:
                new_lines.append(line)

        if replaced_branch and replaced_worktree and replaced_owner:
            with open(plan_file, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            return

        # 없으면 상태 줄 다음에 삽입 (없으면 첫 번째 # 제목 다음)
        insert_idx = None
        for i, line in enumerate(new_lines):
            if re.match(r"^>\s*상태:", line):
                insert_idx = i + 1
                break
        if insert_idx is None:
            for i, line in enumerate(new_lines):
                if line.startswith("#"):
                    insert_idx = i + 1
                    break
        if insert_idx is None:
            insert_idx = 0

        inserts = []
        if not replaced_branch:
            inserts.append(branch_line)
        if not replaced_worktree:
            inserts.append(worktree_line)
        if not replaced_owner:
            inserts.append(owner_line)
        new_lines = new_lines[:insert_idx] + inserts + new_lines[insert_idx:]

        with open(plan_file, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception as e:
        logger.warning(f"[write_plan_worktree_info] 기록 실패 (무시): {e}")


def get_plan_completion(plan_file: str | None) -> tuple[int, int]:
    """plan 파일의 체크박스 완료율 계산.

    코드블럭(``` 내부) 체크박스는 카운트 제외.

    Args:
        plan_file: plan 파일 경로. None이거나 파일 없으면 (0, 0) 반환.

    Returns:
        (done_count, total_count)
    """
    if not plan_file:
        return (0, 0)
    try:
        with open(plan_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return (0, 0)

    done = 0
    total = 0
    in_codeblock = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_codeblock = not in_codeblock
            continue
        if in_codeblock:
            continue
        if re.search(r"-\s\[x\]", stripped, re.IGNORECASE):
            done += 1
            total += 1
        elif re.search(r"-\s\[ \]", stripped):
            total += 1
    return (done, total)


def is_fix_plan(file_path: str, content: str = "") -> bool:
    """fix plan 여부 판정 (Phase R 필수 대상)"""
    name = Path(file_path).name
    if "_fix-" in name or "_fix_" in name:
        return True
    if content:
        for line in content.split("\n")[:5]:
            if line.startswith("# fix") and len(line) > 5 and line[5] in (":", "-", " "):
                return True
        if re.search(r">\s*유형:\s*fix", content[:1000]):
            return True
    return False


def has_phase_r(content: str) -> bool:
    """Phase R 섹션 존재 여부"""
    return "Phase R" in content or "재발 경로 분석" in content


def has_undefended_paths(content: str) -> bool:
    """Phase R 내 실제 '미방어' 경로 잔존 여부.

    _plan_header_utils 공통 구현으로 위임해 code block 제외와 완료형 문구 제외
    규칙을 validate_done_preconditions()와 동일하게 유지한다.
    """
    import sys as _sys
    _project_root = str(Path(__file__).resolve().parent.parent.parent)
    if _project_root not in _sys.path:
        _sys.path.insert(0, _project_root)
    from app.modules.dev_runner.services._plan_header_utils import has_undefended_paths as _utils_has_undefended
    return _utils_has_undefended(content)


def validate_done_preconditions(file_path: str, content: str) -> list:
    """done 처리 전 사전 검증. 실패 사유 리스트 반환 (빈 리스트 = 통과)

    _plan_header_utils 공통 구현으로 위임 (re-export).
    이 함수는 하위 호환성 유지용으로 존재한다.
    """
    import sys as _sys
    _project_root = str(Path(__file__).resolve().parent.parent.parent)
    if _project_root not in _sys.path:
        _sys.path.insert(0, _project_root)
    from app.modules.dev_runner.services._plan_header_utils import validate_done_preconditions as _utils_validate
    return _utils_validate(file_path, content)


def remove_plan_header_fields(plan_file: str):
    """plan 파일에서 '> branch:' / '> worktree:' / '> worktree-owner:' 줄 제거"""
    try:
        with open(plan_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        new_lines = [l for l in lines if not re.match(r"^>\s*(branch|worktree-owner|worktree):", l)]
        with open(plan_file, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception as e:
        logger.warning(f"[remove_plan_header_fields] 제거 실패 (무시): {e}")
