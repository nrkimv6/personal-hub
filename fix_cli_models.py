import sys
import re

filepath = r'D:\work\project\service\wtools\common\tools\plan-runner\cli.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace auto-plan call
old_plan = '''        result = await self.executor.run(engine=self.engine,
            prompt=prompt,
            agent="auto-plan",
            model=self.config.models.get("plan", "opus")
        )'''
new_plan = '''        engine_cfg = self.config.get_engine_config(self.engine)
        result = await self.executor.run(engine=self.engine,
            prompt=prompt,
            agent="auto-plan",
            model=engine_cfg.get("models", {}).get("plan", engine_cfg.get("default_model"))
        )'''
if old_plan in content:
    content = content.replace(old_plan, new_plan)
    print("Replaced plan call")

# Replace auto-impl call
old_impl = '''            result = await self.executor.run(engine=self.engine,
                prompt=prompt,
                agent="auto-impl",
                model=self.config.models.get("impl", "sonnet")
            )'''
new_impl = '''            engine_cfg = self.config.get_engine_config(self.engine)
            result = await self.executor.run(engine=self.engine,
                prompt=prompt,
                agent="auto-impl",
                model=engine_cfg.get("models", {}).get("impl", engine_cfg.get("default_model"))
            )'''
if old_impl in content:
    content = content.replace(old_impl, new_impl)
    print("Replaced impl call")

# Replace auto-done call
old_done = '''        try:
            result = await self.executor.run(
                prompt=prompt,
                model=self.config.models.get("done", "sonnet")
                # agent ?: /done? ?
쎄(slash command)??嚥?--agent 븍釉
            )'''
new_done = '''        try:
            engine_cfg = self.config.get_engine_config(self.engine)
            result = await self.executor.run(
                engine=self.engine,
                prompt=prompt,
                model=engine_cfg.get("models", {}).get("done", engine_cfg.get("default_model"))
            )'''
if old_done in content:
    content = content.replace(old_done, new_done)
    print("Replaced done call")

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

