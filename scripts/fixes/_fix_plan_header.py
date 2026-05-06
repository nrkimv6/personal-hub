from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "plan_runner"))

from plan_worktree_helpers import resolve_active_plan_file


DEFAULT_PLAN = "docs/plan/2026-03-03_dev-runner-design-port-v2_todo.md"


def main() -> int:
    requested = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PLAN
    target = resolve_active_plan_file(requested, project_root=REPO_ROOT)
    if target is None:
        print(f"Plan file not found: {requested}")
        return 1

    content = target.read_text(encoding="utf-8")

    old = "> 상태: 진행중"
    new = "> 상태: 구현중"
    print(f"old found: {old in content}")
    content = content.replace(old, new, 1)

    old2 = "> 진행률: 14/18 (78%)"
    new2 = (
        "> 진행률: 14/18 (78%)\n"
        "> branch: impl/dev-runner-design-port-v2\n"
        "> worktree: .worktrees/impl-dev-runner-design-port-v2"
    )
    print(f"progress found: {old2 in content}")
    content = content.replace(old2, new2, 1)

    target.write_text(content, encoding="utf-8")
    print(f"Done: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
