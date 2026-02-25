import sys
import re

filepath = r'D:\work\project\service\wtools\common\tools\plan-runner\cli.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix duplicated cwd in _run_auto_plan
content = re.sub(
    r'cwd=str\(project_dir\),\s*cwd=str\(project_dir\)',
    r'cwd=str(project_dir)',
    content
)

# Also check other places
content = re.sub(
    r'cwd=str\(project_dir\) if project_dir else None,\s*cwd=str\(project_dir\) if project_dir else None',
    r'cwd=str(project_dir) if project_dir else None',
    content
)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print("cli.py duplicated cwd fixed.")
