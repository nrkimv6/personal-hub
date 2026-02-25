import sys
import re

filepath = r'D:\work\project\service\wtools\common\tools\plan-runner\core\executor.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update _build_gemini_command signature and logic
old_gemini_sig = '''    def _build_gemini_command(
        self,
        prompt: str,
        model: Optional[str] = None,
        flags: Optional[List[str]] = None
    ) -> List[str]:'''

new_gemini_sig = '''    def _build_gemini_command(
        self,
        prompt: str,
        model: Optional[str] = None,
        flags: Optional[List[str]] = None,
        include_dirs: Optional[List[str]] = None
    ) -> List[str]:'''

if old_gemini_sig in content:
    content = content.replace(old_gemini_sig, new_gemini_sig)
    
old_gemini_flags = '''        # ?域?(e.g., --yolo)
        if flags:
            cmd.extend(flags)

        # ?袁⑨세?袁る (-p)
        cmd.extend(["-p", prompt])'''
        
new_gemini_flags = '''        # 플래그 (e.g., --yolo)
        if flags:
            cmd.extend(flags)

        if include_dirs:
            for d in include_dirs:
                cmd.extend(["--include-directories", str(d)])

        # 프롬프트 (-p)
        cmd.extend(["-p", prompt])'''

if old_gemini_flags in content:
    content = content.replace(old_gemini_flags, new_gemini_flags)
else:
    # try regex fallback
    content = re.sub(
        r'(cmd\.extend\(flags\)\n\n\s*# [^\n]*\n\s*cmd\.extend\(\["-p", prompt\]\))',
        r'cmd.extend(flags)\n\n        if include_dirs:\n            for d in include_dirs:\n                cmd.extend(["--include-directories", str(d)])\n\n        # 프롬프트 (-p)\n        cmd.extend(["-p", prompt])',
        content
    )

# 2. Update run signature
old_run_sig = '''    async def run(
        self,
        prompt: str,
        engine: Optional[str] = None,
        agent: Optional[str] = None,
        model: Optional[str] = None,
        allowed_tools: Optional[List[str]] = None
    ) -> ExecutionResult:'''

new_run_sig = '''    async def run(
        self,
        prompt: str,
        engine: Optional[str] = None,
        agent: Optional[str] = None,
        model: Optional[str] = None,
        allowed_tools: Optional[List[str]] = None,
        include_dirs: Optional[List[str]] = None
    ) -> ExecutionResult:'''

if old_run_sig in content:
    content = content.replace(old_run_sig, new_run_sig)

# 3. Pass include_dirs to _build_gemini_command
old_build_call = '''        if target_engine == "gemini":
            cmd = self._build_gemini_command(prompt, target_model, engine_cfg.get("flags"))'''

new_build_call = '''        if target_engine == "gemini":
            cmd = self._build_gemini_command(prompt, target_model, engine_cfg.get("flags"), include_dirs)'''

if old_build_call in content:
    content = content.replace(old_build_call, new_build_call)


with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print("executor.py updated with include_dirs.")
