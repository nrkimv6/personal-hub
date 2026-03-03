"""
plan 파일 헤더에서 워크트리 정보를 읽고 쓰는 헬퍼 함수 모음.

dev-runner-command-listener.py 및 테스트에서 공유 사용.
"""
import re
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


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


def write_plan_worktree_info(plan_file: str, branch: str, worktree_rel: str):
    """plan 파일 헤더에 branch/worktree 기록 (이미 있으면 교체, 없으면 상태 줄 다음에 삽입)"""
    try:
        with open(plan_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        branch_line = f"> branch: {branch}\n"
        worktree_line = f"> worktree: {worktree_rel}\n"

        # 이미 존재하면 교체
        new_lines = []
        replaced_branch = False
        replaced_worktree = False
        for line in lines:
            if re.match(r"^>\s*branch:", line):
                new_lines.append(branch_line)
                replaced_branch = True
            elif re.match(r"^>\s*worktree:", line):
                new_lines.append(worktree_line)
                replaced_worktree = True
            else:
                new_lines.append(line)

        if replaced_branch and replaced_worktree:
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
        new_lines = new_lines[:insert_idx] + inserts + new_lines[insert_idx:]

        with open(plan_file, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception as e:
        logger.warning(f"[write_plan_worktree_info] 기록 실패 (무시): {e}")


def remove_plan_header_fields(plan_file: str):
    """plan 파일에서 '> branch:' / '> worktree:' 줄 제거"""
    try:
        with open(plan_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        new_lines = [l for l in lines if not re.match(r"^>\s*(branch|worktree):", l)]
        with open(plan_file, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception as e:
        logger.warning(f"[remove_plan_header_fields] 제거 실패 (무시): {e}")
