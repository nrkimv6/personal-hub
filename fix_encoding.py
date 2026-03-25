import re

path = 'D:/work/project/service/wtools/.worktrees/impl-fix-test-runner-patch-path-and-line-num/common/tools/plan-runner/tests/test_runner.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# write_text without encoding -> add encoding='utf-8'
fixed = re.sub(
    r'\.write_text\(([^)]+)\)',
    lambda m: '.write_text(' + m.group(1) + ', encoding="utf-8")' if 'encoding' not in m.group(1) else m.group(0),
    content
)

changes = content.count('.write_text(')
with open(path, 'w', encoding='utf-8') as f:
    f.write(fixed)
print(f'Fixed {changes} write_text calls')
