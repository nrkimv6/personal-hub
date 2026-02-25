import sys
import re

filepath = r'D:\work\project\service\wtools\common\tools\plan-runner\cli.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

matches = re.findall(r"await self\.executor\.run\([^)]+\)", content, re.MULTILINE | re.DOTALL)
for match in matches:
    print("---")
    print(match)

