import sys
import re

filepath = r'D:\work\project\service\wtools\common\tools\plan-runner\core\executor.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Update claude path logic to check for .exe too
old_claude_logic = '''        if _sys.platform == "win32" and not cli_path.lower().endswith(".cmd") and not cli_path.lower().endswith(".exe"):
            if not _os.path.exists(cli_path) and _os.path.exists(cli_path + ".cmd"):
                cli_path += ".cmd"
            elif not _os.path.exists(cli_path):
                # Fallback to appending .cmd if nothing exists, allowing PATH resolution to try it
                cli_path += ".cmd"'''

new_claude_logic = '''        if _sys.platform == "win32" and not cli_path.lower().endswith((".cmd", ".exe")):
            if _os.path.exists(cli_path + ".exe"):
                cli_path += ".exe"
            elif _os.path.exists(cli_path + ".cmd"):
                cli_path += ".cmd"
            else:
                # If neither exists but it is a base name, it might be in PATH.
                # But here it seems to be a full path from config.
                pass'''

if old_claude_logic in content:
    content = content.replace(old_claude_logic, new_claude_logic)
else:
    # try to find the start of the logic
    content = re.sub(
        r'if _sys\.platform == "win32" and not cli_path\.lower\(\)\.endswith\(".cmd"\) and not cli_path\.lower\(\)\.endswith\(".exe"\):.*?cli_path \+= "\.cmd"',
        new_claude_logic,
        content,
        flags=re.DOTALL
    )

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print("executor.py updated with .exe support for claude.")
