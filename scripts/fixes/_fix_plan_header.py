from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_ROOT = REPO_ROOT / ".worktrees" / "plans" / "docs" / "plan"
TARGET_FILE = PLAN_ROOT / "2026-03-03_dev-runner-design-port-v2_todo.md"


with TARGET_FILE.open("r", encoding="utf-8") as handle:
    content = handle.read()

old = "> 상태: 진행중"
new = "> 상태: 구현중"
print(f"old found: {old in content}")
content = content.replace(old, new, 1)

# branch/worktree 추가 (진행률 뒤에)
old2 = "> 진행률: 14/18 (78%)"
new2 = (
    "> 진행률: 14/18 (78%)\n"
    "> branch: impl/dev-runner-design-port-v2\n"
    "> worktree: .worktrees/impl-dev-runner-design-port-v2"
)
print(f"progress found: {old2 in content}")
content = content.replace(old2, new2, 1)

with TARGET_FILE.open("w", encoding="utf-8") as handle:
    handle.write(content)

print(f"Done: {TARGET_FILE}")
