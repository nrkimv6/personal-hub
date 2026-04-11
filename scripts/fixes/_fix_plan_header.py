path = r'D:\work\project\tools\monitor-page\docs\plan\2026-03-03_dev-runner-design-port-v2_todo.md'
with open(path, 'r', encoding='utf-8') as f:
    c = f.read()

old = '> \uc0c1\ud0dc: \uc9c4\ud589\uc911'
new = '> \uc0c1\ud0dc: \uad6c\ud604\uc911'
print(f"old found: {old in c}")
c = c.replace(old, new, 1)

# branch/worktree 추가 (진행률 뒤에)
old2 = '> \uc9c4\ud589\ub960: 14/18 (78%)'
new2 = '> \uc9c4\ud589\ub960: 14/18 (78%)\n> branch: impl/dev-runner-design-port-v2\n> worktree: .worktrees/impl-dev-runner-design-port-v2'
print(f"progress found: {old2 in c}")
c = c.replace(old2, new2, 1)

with open(path, 'w', encoding='utf-8') as f:
    f.write(c)
print("Done")
