import sys
import re

filepath = r'D:\work\project\service\wtools\common\tools\plan-runner\cli.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. auto-plan
content = re.sub(
    r'result = await self\.executor\.run\(engine=self\.engine,\s*prompt=prompt,\s*agent="auto-plan",\s*model=self\.config\.models\.get\("plan", "opus"\)\s*\)',
    r'''engine_cfg = self.config.get_engine_config(self.engine)
        result = await self.executor.run(engine=self.engine,
            prompt=prompt,
            agent="auto-plan",
            model=engine_cfg.get("models", {}).get("plan", engine_cfg.get("default_model"))
        )''',
    content
)

# 2. auto-impl
content = re.sub(
    r'result = await self\.executor\.run\(engine=self\.engine,\s*prompt=prompt,\s*agent="auto-impl",\s*model=self\.config\.models\.get\("impl", "sonnet"\)\s*\)',
    r'''engine_cfg = self.config.get_engine_config(self.engine)
            result = await self.executor.run(engine=self.engine,
                prompt=prompt,
                agent="auto-impl",
                model=engine_cfg.get("models", {}).get("impl", engine_cfg.get("default_model"))
            )''',
    content
)

# 3. auto-done
content = re.sub(
    r'result = await self\.executor\.run\(\s*prompt=prompt,\s*model=self\.config\.models\.get\("done", "sonnet"\).*?\)',
    r'''engine_cfg = self.config.get_engine_config(self.engine)
            result = await self.executor.run(
                engine=self.engine,
                prompt=prompt,
                model=engine_cfg.get("models", {}).get("done", engine_cfg.get("default_model"))
            )''',
    content,
    flags=re.DOTALL
)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print("Regex replacements executed.")
