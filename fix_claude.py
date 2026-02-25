import sys
import re

filepath = r'D:\work\project\service\wtools\common\tools\plan-runner\core\executor.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

old_str = '        cmd = [self.config.claude_cli_path]'
new_str = '''        cli_path = self.config.claude_cli_path
        import sys as _sys
        import os as _os
        if _sys.platform == "win32" and not cli_path.lower().endswith(".cmd") and not cli_path.lower().endswith(".exe"):
            if not _os.path.exists(cli_path) and _os.path.exists(cli_path + ".cmd"):
                cli_path += ".cmd"
            elif not _os.path.exists(cli_path):
                # Fallback to appending .cmd if nothing exists, allowing PATH resolution to try it
                cli_path += ".cmd"
        cmd = [cli_path]'''

if old_str in content:
    content = content.replace(old_str, new_str)
    print("Replaced claude executable logic correctly.")
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
else:
    print("Could not find the claude command definition.")

