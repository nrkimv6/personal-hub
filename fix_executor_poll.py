import os
import re

filepath = r'D:\work\project\service\wtools\common\tools\plan-runner\core\executor.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix .poll() -> .returncode
content = content.replace('if process.poll() is not None:', 'if process.returncode is not None:')

# Re-verify Indentation around asyncio.create_subprocess_exec
# I will rewrite the whole run method again to be 100% sure about indentation.
# Based on the previous read, the start of 'run' method was line 293 (0-indexed 292).

lines = content.splitlines(keepends=True)
start_idx = -1
for i, line in enumerate(lines):
    if 'async def run(' in line:
        start_idx = i
        break

if start_idx != -1:
    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        if re.match(r'^\s{4}(async )?def ', lines[i]):
            end_idx = i
            break
    
    # Use the clean version I have
    new_run_method = """    async def run(
        self,
        prompt: str,
        engine: Optional[str] = None,
        agent: Optional[str] = None,
        model: Optional[str] = None,
        allowed_tools: Optional[List[str]] = None,
        include_dirs: Optional[List[str]] = None,
        cwd: Optional[str] = None
    ) -> ExecutionResult:
        \"\"\"
        AI 실행 (Claude 또는 Gemini)
        \"\"\"
        target_engine = engine or self.config.engine
        engine_cfg = self.config.get_engine_config(target_engine)

        # 모델 결정 (매핑 우선 -> 기본값)
        target_model = model or engine_cfg.get("models", {}).get(agent, engine_cfg.get("default_model"))

        if target_engine == "gemini":
            cmd = self._build_gemini_command(prompt, target_model, engine_cfg.get("flags"), include_dirs)
            stdin_prompt = None
        else:
            cmd, stdin_prompt = self._build_command(prompt, agent, target_model, allowed_tools)

        # cycle 시작 시 로그 기록 관련 초기화
        self._accumulated_output.clear()
        self._last_analyzed_idx = 0
        # CycleOutputAnalyzer lazy init
        if (
            self.config.ai_response_auto_check
            and self._ai_analyzer is None
            and self.syncer is not None
        ):
            try:
                from .cycle_analyzer import CycleOutputAnalyzer
                self._ai_analyzer = CycleOutputAnalyzer(model=self.config.ai_check_model)
            except Exception as _e:
                logger.debug("[AI-CHECK] CycleOutputAnalyzer 초기화 실패: %s", _e)

        log_path = self._open_log()

        try:
            # 환경변수 구성: CI 모드 강제 및 불필요한 콘솔 에뮬레이션 방지 (AttachConsole 에러 해결)
            env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
            env["CI"] = "true"
            env["TERM"] = "dumb"
            env["NO_COLOR"] = "1"
            env["PYTHONUNBUFFERED"] = "1"

            # subprocess 실행
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE if stdin_prompt else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=1024 * 1024,  # 1MB
                cwd=cwd or str(self.config.base_dir),
                env=env
            )

            # stdin으로 프롬프트 전달 (긴 프롬프트용)
            if stdin_prompt:
                process.stdin.write(stdin_prompt.encode('utf-8'))
                await process.stdin.drain()
                process.stdin.close()

            # stdout 실시간 읽기
            output_lines = []

            async def _read_stderr():
                \"\"\"stderr를 비동기로 읽어 누적 + 실시간 출력\"\"\"
                while True:
                    line = await process.stderr.readline()
                    if not line:
                        break
                    decoded = line.decode('utf-8', errors='replace').rstrip()
                    self._stderr_lines.append(decoded)
                    if decoded.strip():
                        ts = datetime.now().strftime("%H:%M:%S")
                        print(f"  \\033[90m[{ts}]\\033[0m \\033[91m[STDERR]\\033[0m {decoded[:200]}")
                        if self._log_file:
                            self._log_file.write(f"[{ts}] [STDERR] {decoded}\\n")
                            self._log_file.flush()

            stderr_task = asyncio.create_task(_read_stderr())

            try:
                deadline = asyncio.get_event_loop().time() + self.config.task_timeout_seconds
                last_output_time = asyncio.get_event_loop().time()
                heartbeat_interval = 30
                readline_chunk_timeout = 10
                while True:
                    now = asyncio.get_event_loop().time()
                    remaining = deadline - now
                    if remaining <= 0:
                        process.kill()
                        await process.wait()
                        return ExecutionResult(
                            success=False, status="timeout", output="",
                            error=f"Task timeout after {self.config.task_timeout_seconds}s"
                        )

                    try:
                        line = await asyncio.wait_for(process.stdout.readline(), timeout=readline_chunk_timeout)
                    except asyncio.TimeoutError:
                        if process.returncode is not None:
                            break
                        wait_duration = asyncio.get_event_loop().time() - last_output_time
                        if wait_duration >= heartbeat_interval:
                            ts = datetime.now().strftime("%H:%M:%S")
                            print(f"  \\033[90m[{ts}]\\033[0m \\033[34m[ALIVE]\\033[0m 대기 중... (PID:{process.pid}, 무출력 {int(wait_duration)}s)")
                            last_output_time = asyncio.get_event_loop().time()
                        continue

                    if not line:
                        break
                    last_output_time = asyncio.get_event_loop().time()
                    decoded = line.decode('utf-8', errors='replace').rstrip()
                    output_lines.append(decoded)
                    self._ai_check_pending = False
                    if target_engine == \"gemini\":
                        self._stream_gemini_line(decoded)
                    else:
                        self._stream_line(decoded)
                    if self._ai_check_pending:
                        self._ai_check_pending = False
                        await self._run_ai_check()

            except Exception:
                raise
            finally:
                await stderr_task

            await process.wait()
            stdout = "\\n".join(output_lines)
            stderr = "\\n".join(self._stderr_lines)

            # 결과 파싱
            if target_engine == \"gemini\":
                result = self._parse_gemini_output(stdout, stderr, process.returncode, target_model)
            else:
                result = self._parse_output(stdout, stderr, process.returncode)

            return result

        except Exception as e:
            # 예외 발생 시: 에러 로그 기록
            error_time = datetime.now().isoformat()
            error_msg = f"[{error_time}] ERROR | {type(e).__name__}: {str(e)}"
            import traceback
            traceback_msg = f"Traceback:\\n{traceback.format_exc()}"

            if self._log_file:
                self._log_file.write(f"{error_msg}\\n")
                self._log_file.write(f"{traceback_msg}\\n")
                self._log_file.flush()

            print(f"  \\033[91m{error_msg}\\033[0m")
            return ExecutionResult(success=False, status=\"error\", output=\"\", error=str(e))
"""
    new_content = "".join(lines[:start_idx]) + new_run_method + "\\n" + "".join(lines[end_idx:])
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("executor.py fixed and poll replaced.")
else:
    print("Failed to find run method.")
