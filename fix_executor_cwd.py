import sys
import re

filepath = r'D:\work\project\service\wtools\common\tools\plan-runner\core\executor.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update run signature to accept cwd
old_run_sig = '''    async def run(
        self,
        prompt: str,
        engine: Optional[str] = None,
        agent: Optional[str] = None,
        model: Optional[str] = None,
        allowed_tools: Optional[List[str]] = None,
        include_dirs: Optional[List[str]] = None
    ) -> ExecutionResult:'''

new_run_sig = '''    async def run(
        self,
        prompt: str,
        engine: Optional[str] = None,
        agent: Optional[str] = None,
        model: Optional[str] = None,
        allowed_tools: Optional[List[str]] = None,
        include_dirs: Optional[List[str]] = None,
        cwd: Optional[str] = None
    ) -> ExecutionResult:'''

if old_run_sig in content:
    content = content.replace(old_run_sig, new_run_sig)

# 2. Update create_subprocess_exec to use passed cwd or fallback
old_exec = '''                cwd=str(self.config.base_dir),'''
new_exec = '''                cwd=cwd or str(self.config.base_dir),'''

if old_exec in content:
    content = content.replace(old_exec, new_exec)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print("executor.py updated with cwd support.")
