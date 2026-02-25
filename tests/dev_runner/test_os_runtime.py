import sys
import asyncio
import pytest
from pathlib import Path

# 모듈 로드를 위한 경로 처리
WTOOLS_BASE_DIR = Path(r"D:\work\project\service\wtools")
PLAN_RUNNER_MODULE_PATH = WTOOLS_BASE_DIR / "common/tools/plan-runner"
sys.path.insert(0, str(PLAN_RUNNER_MODULE_PATH))

from plan_runner.core.executor import AIExecutor
from plan_runner.config import Settings

class TestOSRuntimeDependencies:
    """[WinError 2]와 같은 실행 파일 시스템 의존성 문제를 잡기 위한 테스트"""

    @pytest.fixture
    def executor(self):
        config = Settings()
        return AIExecutor(config)

    @pytest.mark.asyncio
    async def test_gemini_subprocess_exec_resolution(self, executor):
        """Right - gemini 엔진이 현재 OS에서 정상적으로 subprocess로 띄워지는가?"""
        # 실제 프롬프트 전송이 아닌 --help 플래그 등을 통해 바이너리 존재 여부만 검증
        target_engine = "gemini"
        engine_cfg = executor.config.get_engine_config(target_engine)
        
        # gemini 내부 커맨드 빌더 호출
        cmd = executor._build_gemini_command("ping", None, ["--help"])
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            # 프로세스가 정상적으로 떴고 0 코드 반환
            assert process.returncode == 0, f"gemini CLI failed with code {process.returncode}: {stderr.decode()}"
            
        except FileNotFoundError as e:
            pytest.fail(f"[WinError 2] gemini CLI를 시스템에서 찾을 수 없습니다: {e}")

    @pytest.mark.asyncio
    async def test_claude_subprocess_exec_resolution(self, executor):
        """Right - claude 엔진이 현재 OS에서 정상적으로 subprocess로 띄워지는가?"""
        # Claude CLI 역시 .cmd 확장자 누락 등으로 실패할 가능성이 있음
        cmd, _ = executor._build_command("ping", None, None, None)
        
        # Claude는 --help 지원 여부에 따라 다르므로, 버전 확인이나 존재 여부만 체크
        if sys.platform == "win32" and not cmd[0].endswith(".cmd") and not cmd[0].endswith(".exe"):
            # 시스템에 따라 .cmd를 붙여야 할 수 있음. (이 테스트는 현재 설정의 견고함을 검증함)
            # 설정 경로에 파일이 실제로 존재하는지 우선 확인
            executable = Path(cmd[0])
            if not executable.exists() and not executable.with_suffix('.cmd').exists():
                 pytest.fail(f"Claude CLI 경로를 찾을 수 없습니다: {cmd[0]}")
