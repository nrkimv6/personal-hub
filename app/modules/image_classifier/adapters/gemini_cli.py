"""
Gemini CLI 어댑터 (Claude CLI fallback용)
"""

import asyncio
import json
import logging
from typing import Optional, Callable

from .base import ClassifierAdapter, ClassifyResult
from ..config import settings

logger = logging.getLogger(__name__)


class GeminiCLIAdapter(ClassifierAdapter):
    """Gemini CLI 어댑터 (Claude CLI 대체/보조)"""

    def __init__(self, cli_path: Optional[str] = None, on_output: Optional[Callable[[str], None]] = None):
        self.cli_path = cli_path or settings.GEMINI_CLI_PATH
        self.timeout = settings.CLI_TIMEOUT_SECONDS
        self.on_output = on_output  # 실시간 stderr 콜백

    async def classify_image(
        self,
        image_path: str,
        prompt: str,
        categories: list[str],
    ) -> ClassifyResult:
        """단일 이미지 분류"""
        full_prompt = self._build_prompt(prompt, categories, [image_path])

        try:
            result = await asyncio.wait_for(
                self._run_cli(full_prompt),
                timeout=self.timeout
            )

            return ClassifyResult(
                category_path=result.get("category", "unknown"),
                confidence=float(result.get("confidence", 0.5)),
                reasoning=result.get("reasoning"),
                model="gemini-1.5-flash (CLI)"
            )

        except Exception as e:
            return ClassifyResult(
                category_path="error/exception",
                confidence=0.0,
                reasoning=str(e),
                model="gemini (CLI)"
            )

    async def classify_images_batch(
        self,
        image_paths: list[str],
        prompt: str,
        categories: list[str],
    ) -> list[ClassifyResult]:
        """배치 분류 (단일 이미지 분류를 순차 실행)"""
        results = []
        for img_path in image_paths:
            result = await self.classify_image(img_path, prompt, categories)
            results.append(result)
        return results

    async def _run_cli(self, prompt: str) -> dict:
        """Gemini CLI subprocess 실행 — stderr 실시간 스트리밍"""
        cmd = [
            self.cli_path,
            "-p", prompt,
            "--output-format", "json"
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # stderr 실시간 읽기
        stderr_lines = []

        async def _stream_stderr():
            while True:
                line = await proc.stderr.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").strip()
                if decoded:
                    stderr_lines.append(decoded)
                    if self.on_output:
                        self.on_output(decoded)

        stderr_task = asyncio.create_task(_stream_stderr())
        stdout_data = await proc.stdout.read()
        await stderr_task
        await proc.wait()

        if proc.returncode != 0:
            stderr_text = "\n".join(stderr_lines) if stderr_lines else "(no stderr)"
            raise RuntimeError(f"Gemini CLI exit {proc.returncode}: {stderr_text}")

        try:
            return json.loads(stdout_data.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as e:
            stdout_preview = stdout_data.decode("utf-8", errors="replace")[:200]
            raise RuntimeError(f"JSON 파싱 실패: {e} — stdout: {stdout_preview}")

    def _build_prompt(self, context: str, categories: list[str], image_paths: list[str]) -> str:
        """프롬프트 생성"""
        cat_list = "\n".join(f"- {cat}" for cat in categories)
        img_list = "\n".join(f"- {path}" for path in image_paths)

        return f"""
다음 이미지를 아래 카테고리 중 하나로 분류하세요.

**컨텍스트:**
{context}

**가능한 카테고리:**
{cat_list}

**이미지 파일:**
{img_list}

JSON 형식으로 응답하세요:
{{
    "category": "카테고리 경로",
    "confidence": 0.8,
    "reasoning": "분류 이유"
}}
"""

    def get_model_name(self) -> str:
        return "gemini-1.5-flash (CLI)"

    async def is_available(self) -> bool:
        """CLI 실행 가능 여부 확인"""
        try:
            proc = await asyncio.create_subprocess_exec(
                self.cli_path, "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()
            return proc.returncode == 0
        except FileNotFoundError:
            return False
