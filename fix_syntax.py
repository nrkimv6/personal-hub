import sys
import re

filepath = r'D:\work\project\service\wtools\common\tools\plan-runner\cli.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the syntax error in done call
# The bad part is )??嚥?--agent 븍釉\n            )
# We just need to replace the specific corrupted block:
bad_string = '''            result = await self.executor.run(
                engine=self.engine,
                prompt=prompt,
                model=engine_cfg.get("models", {}).get("done", engine_cfg.get("default_model"))
            )??嚥?--agent 븍釉
            )'''

good_string = '''            result = await self.executor.run(
                engine=self.engine,
                prompt=prompt,
                model=engine_cfg.get("models", {}).get("done", engine_cfg.get("default_model"))
            )'''

if bad_string in content:
    content = content.replace(bad_string, good_string)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Syntax error fixed.")
else:
    # try regex for anything resembling it
    pattern = re.compile(r'model=engine_cfg\.get\("models", \{\}\)\.get\("done", engine_cfg\.get\("default_model"\)\)\n\s*\).*?\)', re.DOTALL)
    new_content = pattern.sub(r'model=engine_cfg.get("models", {}).get("done", engine_cfg.get("default_model"))\n            )', content)
    if content != new_content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("Syntax error fixed via regex.")
    else:
        print("Syntax error string not found.")
