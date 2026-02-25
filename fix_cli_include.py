import sys
import re

filepath = r'D:\work\project\service\wtools\common\tools\plan-runner\cli.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update _run_auto_plan
old_plan_call = '''        result = await self.executor.run(engine=self.engine,
            prompt=prompt,
            agent="auto-plan",
            model=engine_cfg.get("models", {}).get("plan", engine_cfg.get("default_model"))
        )'''
new_plan_call = '''        project_dir = get_project_dir(plan_file, self.config.base_dir)
        result = await self.executor.run(engine=self.engine,
            prompt=prompt,
            agent="auto-plan",
            model=engine_cfg.get("models", {}).get("plan", engine_cfg.get("default_model")),
            include_dirs=[str(project_dir)]
        )'''
if old_plan_call in content:
    content = content.replace(old_plan_call, new_plan_call)

# 2. Update _run_auto_impl
old_impl_call = '''            result = await self.executor.run(engine=self.engine,
                prompt=prompt,
                agent="auto-impl",
                model=engine_cfg.get("models", {}).get("impl", engine_cfg.get("default_model"))
            )'''
new_impl_call = '''            project_dir = get_project_dir(plan_file, self.config.base_dir) if plan_file else None
            include_dirs = [str(project_dir)] if project_dir else None
            result = await self.executor.run(engine=self.engine,
                prompt=prompt,
                agent="auto-impl",
                model=engine_cfg.get("models", {}).get("impl", engine_cfg.get("default_model")),
                include_dirs=include_dirs
            )'''
if old_impl_call in content:
    content = content.replace(old_impl_call, new_impl_call)

# 3. Update _run_auto_done_via_cli
# For done, it also needs project_dir
old_done_call = '''            result = await self.executor.run(
                engine=self.engine,
                prompt=prompt,
                model=engine_cfg.get("models", {}).get("done", engine_cfg.get("default_model"))
            )'''
new_done_call = '''            project_dir = get_project_dir(plan_file, self.config.base_dir)
            result = await self.executor.run(
                engine=self.engine,
                prompt=prompt,
                model=engine_cfg.get("models", {}).get("done", engine_cfg.get("default_model")),
                include_dirs=[str(project_dir)]
            )'''
if old_done_call in content:
    content = content.replace(old_done_call, new_done_call)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print("cli.py updated to pass include_dirs.")
