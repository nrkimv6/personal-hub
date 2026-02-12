"""
Gemini CLI 어댑터 (Claude CLI fallback용)
"""

import asyncio
import json
import subprocess
from typing import Optional

from .base import ClassifierAdapter, ClassifyResult
from ..config import settings


class GeminiCLIAdapter(ClassifierAdapter):
    """Gemini CLI 어댑터 (Claude CLI 대체/보조)"""

    def __init__(self, cli_path: Optional[str] = None):
        self.cli_path = cli_path or settings.GEMINI_CLI_PATH
        self.timeout = settings.CLI_TIMEOUT_SECONDS

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
        """Gemini CLI subprocess 실행 (간단한 JSON 응답 파싱)"""
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

        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"Gemini CLI 오류: {stderr.decode()}")

        return json.loads(stdout.decode())

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
