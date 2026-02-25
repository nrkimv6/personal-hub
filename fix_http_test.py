import sys
import re

filepath = r'D:\work\project\tools\monitor-page\tests\dev_runner\test_http_e2e.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the syntax error in the print statement
pattern = r'print\(f"\\n\[SUCCESS\] HTTP E2E  援ш  명 \(PID: \{r\.get\(\'plan-runner:state:pid\'\)\}\)"\)'
replacement = "print(f'\\n[SUCCESS] HTTP E2E Connection Verified (PID: {r.get(\"plan-runner:state:pid\")})')"

new_content = re.sub(pattern, replacement, content)

if content == new_content:
    # Try simpler replacement if regex failed due to encoding
    content = content.replace('print(f"\\n[SUCCESS] HTTP E2E  援ш  명', 'print(f"\\n[SUCCESS] HTTP E2E Connection Verified')

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(new_content if content != new_content else content)
