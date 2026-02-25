import sys
import re

filepath = r'D:\work\project\service\wtools\common\tools\plan-runner\cli.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Use regex to find the run function signature
pattern = r"(@app\.command\(\)\ndef run\(\n)(\s+plan_file: Optional\[str\] = typer\.Option)"
replacement = r"\g<1>    engine: str = typer.Option('claude', '--engine', help='AI Engine to use'),\n\g<2>"

new_content = re.sub(pattern, replacement, content)

if content != new_content:
    print("Run signature successfully updated via regex.")
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)
else:
    print("Failed to match run signature via regex.")
