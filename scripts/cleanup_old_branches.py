"""
구형 runner/* 브랜치 일괄 정리 스크립트

전환 기간 중 남은 runner/{id} 형식의 브랜치와 워크트리를 일괄 삭제한다.

사용법:
    python scripts/cleanup_old_branches.py [--dry-run]
"""
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
WORKTREE_BASE_DIR = PROJECT_ROOT / ".worktrees"


def list_runner_branches() -> list[str]:
    result = subprocess.run(
        ["git", "branch", "--list", "runner/*"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
        timeout=30,
    )
    return [line.strip().lstrip("* ") for line in result.stdout.splitlines() if line.strip()]


def list_test_branches() -> list[str]:
    """plan/test_* 패턴 브랜치 목록 반환 — 테스트 잔여 브랜치 정리용."""
    result = subprocess.run(
        ["git", "branch", "--list", "plan/test_*"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
        timeout=30,
    )
    return [line.strip().lstrip("* ") for line in result.stdout.splitlines() if line.strip()]


def list_worktrees() -> list[dict]:
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
        timeout=30,
    )
    worktrees = []
    current: dict = {}
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            current = {"path": line[9:], "branch": None}
        elif line.startswith("branch "):
            current["branch"] = line[7:].replace("refs/heads/", "")
    if current:
        worktrees.append(current)
    return worktrees


def main():
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("[dry-run] 실제 삭제 없이 대상만 출력합니다.")

    branches = list_runner_branches()
    test_branches = list_test_branches()
    worktrees = list_worktrees()

    runner_worktrees = [wt for wt in worktrees if wt.get("branch", "").startswith("runner/")]
    test_worktrees = [wt for wt in worktrees if wt.get("branch", "").startswith("plan/test_")]

    print(f"\n=== runner/* 워크트리: {len(runner_worktrees)}개 ===")
    for wt in runner_worktrees:
        print(f"  {wt['path']} (branch: {wt['branch']})")
        if not dry_run:
            r = subprocess.run(
                ["git", "worktree", "remove", wt["path"], "--force"],
                capture_output=True, text=True, cwd=str(PROJECT_ROOT),
                timeout=30,
            )
            if r.returncode != 0:
                print(f"  [경고] worktree 삭제 실패: {r.stderr.strip()}")
            else:
                print(f"  [완료] worktree 삭제")

    print(f"\n=== plan/test_* 워크트리: {len(test_worktrees)}개 ===")
    for wt in test_worktrees:
        print(f"  {wt['path']} (branch: {wt['branch']})")
        if not dry_run:
            r = subprocess.run(
                ["git", "worktree", "remove", wt["path"], "--force"],
                capture_output=True, text=True, cwd=str(PROJECT_ROOT),
                timeout=30,
            )
            if r.returncode != 0:
                print(f"  [경고] worktree 삭제 실패: {r.stderr.strip()}")
            else:
                print(f"  [완료] worktree 삭제")

    print(f"\n=== runner/* 브랜치: {len(branches)}개 ===")
    for branch in branches:
        print(f"  {branch}")
        if not dry_run:
            r = subprocess.run(
                ["git", "branch", "-D", branch],
                capture_output=True, text=True, cwd=str(PROJECT_ROOT),
                timeout=30,
            )
            if r.returncode != 0:
                print(f"  [경고] 브랜치 삭제 실패: {r.stderr.strip()}")
            else:
                print(f"  [완료] 브랜치 삭제")

    print(f"\n=== plan/test_* 브랜치: {len(test_branches)}개 ===")
    for branch in test_branches:
        print(f"  {branch}")
        if not dry_run:
            r = subprocess.run(
                ["git", "branch", "-D", branch],
                capture_output=True, text=True, cwd=str(PROJECT_ROOT),
                timeout=30,
            )
            if r.returncode != 0:
                print(f"  [경고] 브랜치 삭제 실패: {r.stderr.strip()}")
            else:
                print(f"  [완료] 브랜치 삭제")

    if dry_run:
        print("\n[dry-run 완료] --dry-run 없이 실행하면 위 항목을 삭제합니다.")
    else:
        print("\n[완료] stale 브랜치/워크트리 정리 완료")


if __name__ == "__main__":
    main()
