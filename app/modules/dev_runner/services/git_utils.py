"""dev_runner 공통 git 조회 헬퍼.

NSSM SYSTEM 계정에서 API 실행 시 git 2.35.2+의 CVE-2022-24765 대응 정책으로
폴더 소유권 불일치가 거부되는 문제를 방지하기 위해 `-c safe.directory=*`를 주입한다.

⚠️ 중복 주의: scripts/worktree_manager.py:_run_git에도 동일한 safe.directory 주입 로직이
있다. scripts/와 app/ 간 import 불가로 중복이 불가피하므로, 하나를 수정할 때 반드시 다른 쪽도
함께 확인할 것.
"""
import subprocess
from typing import Optional


def check_branch_exists(branch: str, cwd: Optional[str] = None) -> bool:
    """git branch가 존재하는지 확인. subprocess 실패 시 False (안전 기본값).

    cwd=None 시 프로세스 현재 디렉토리를 사용 (기존 동작 유지).
    """
    try:
        result = subprocess.run(
            ["git", "-c", "safe.directory=*", "branch", "--list", branch],
            cwd=cwd, capture_output=True, text=True, timeout=5
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def check_worktree_exists(worktree_path: str, cwd: Optional[str] = None) -> bool:
    """git worktree가 존재하는지 확인. subprocess 실패 시 False (안전 기본값).

    cwd=None 시 프로세스 현재 디렉토리를 사용 (기존 동작 유지).

    Windows: git worktree list --porcelain 출력은 슬래시(/), 입력 경로는 백슬래시(backslash)일 수 있으므로
    비교 전 슬래시로 정규화한다.
    """
    try:
        result = subprocess.run(
            ["git", "-c", "safe.directory=*", "worktree", "list", "--porcelain"],
            cwd=cwd, capture_output=True, text=True, timeout=5
        )
        # Windows 경로 정규화: 백슬래시 → 슬래시
        normalized_path = worktree_path.replace("\\", "/")
        return normalized_path in result.stdout
    except Exception:
        return False
