import sys
import re

filepath = r'D:\work\project\service\wtools\common\tools\plan-runner\core\executor.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace cmd = ["gemini"] with conditional logic for Windows
old_str = '        cmd = ["gemini"]'
new_str = '        import sys as _sys\n        cmd = ["gemini.cmd" if _sys.platform == "win32" else "gemini"]'

if old_str in content:
    content = content.replace(old_str, new_str)
    print("Replaced gemini executable correctly.")
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
else:
    print("Could not find the gemini command definition.")

