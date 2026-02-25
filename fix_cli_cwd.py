import sys
import re

filepath = r'D:\work\project\service\wtools\common\tools\plan-runner\cli.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update _run_auto_plan
# Previously I added include_dirs=[str(project_dir)]
# Now I will also add cwd=str(project_dir)
content = content.replace(
    'include_dirs=[str(project_dir)]',
    'include_dirs=[str(project_dir)],\n            cwd=str(project_dir)'
)

# 2. Update _run_auto_impl
content = content.replace(
    'include_dirs=include_dirs',
    'include_dirs=include_dirs,\n                cwd=str(project_dir) if project_dir else None'
)

# 3. Update _run_auto_done_via_cli
content = content.replace(
    'include_dirs=[str(project_dir)]',
    'include_dirs=[str(project_dir)],\n                cwd=str(project_dir)'
)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print("cli.py updated to pass cwd.")
