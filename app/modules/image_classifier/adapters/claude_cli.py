"""
Claude CLI 어댑터 (subprocess 기반)

구독 중인 Claude CLI를 프로그래밍적으로 호출하여 이미지 분류 수행.
추가 API 비용 없음 ($0).
"""

import asyncio
import json
import logging
from typing import Optional, Callable

from .base import ClassifierAdapter, ClassifyResult
from ..config import settings

logger = logging.getLogger(__name__)


class ClaudeCLIAdapter(ClassifierAdapter):
    """Claude CLI 어댑터"""

    def __init__(self, cli_path: Optional[str] = None, on_output: Optional[Callable[[str], None]] = None):
        self.cli_path = cli_path or settings.CLAUDE_CLI_PATH
        self.timeout = settings.CLI_TIMEOUT_SECONDS
        self.on_output = on_output  # 실시간 stderr 콜백

    async def classify_image(
        self,
        image_path: str,
        prompt: str,
        categories: list[str],
    ) -> ClassifyResult:
        """단일 이미지 분류"""
        # 프롬프트에 이미지 경로와 카테고리 목록 포함
        full_prompt = self._build_prompt(prompt, categories, [image_path])

        # JSON 스키마 정의
        json_schema = {
            "type": "object",
            "properties": {
                "category": {"type": "string"},
                "confidence": {"type": "number"},
                "reasoning": {"type": "string"}
            },
            "required": ["category", "confidence"]
        }

        try:
            # Claude CLI 호출
            result = await asyncio.wait_for(
                self._run_cli(full_prompt, json_schema),
                timeout=self.timeout
            )

            return ClassifyResult(
                category_path=result.get("category", "unknown"),
                confidence=float(result.get("confidence", 0.5)),
                reasoning=result.get("reasoning"),
                model=f"{settings.CLAUDE_MODEL} (CLI)"
            )

        except asyncio.TimeoutError:
            return ClassifyResult(
                category_path="error/timeout",
                confidence=0.0,
                reasoning="CLI 호출 타임아웃",
                model=f"{settings.CLAUDE_MODEL} (CLI)"
            )

        except Exception as e:
            return ClassifyResult(
                category_path="error/exception",
                confidence=0.0,
                reasoning=str(e),
                model=f"{settings.CLAUDE_MODEL} (CLI)"
            )

    async def classify_images_batch(
        self,
        image_paths: list[str],
        prompt: str,
        categories: list[str],
    ) -> list[ClassifyResult]:
        """배치 분류 (클러스터 단위)"""
        # 배치 프롬프트: 이미지 여러 장을 한 번에 전달
        full_prompt = self._build_prompt(prompt, categories, image_paths)

        # JSON 스키마: 배열 응답
        json_schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "image_path": {"type": "string"},
                    "category": {"type": "string"},
                    "confidence": {"type": "number"},
                    "reasoning": {"type": "string"}
                },
                "required": ["image_path", "category", "confidence"]
            }
        }

        try:
            result = await asyncio.wait_for(
                self._run_cli(full_prompt, json_schema),
                timeout=self.timeout * 2  # 배치는 타임아웃 2배
            )

            # 결과 매핑
            results = []
            result_map = {item["image_path"]: item for item in result}

            for img_path in image_paths:
                item = result_map.get(img_path, {})
                results.append(ClassifyResult(
                    category_path=item.get("category", "unknown"),
                    confidence=float(item.get("confidence", 0.5)),
                    reasoning=item.get("reasoning"),
                    model=f"{settings.CLAUDE_MODEL} (CLI batch)"
                ))

            return results

        except Exception as e:
            # 실패 시 전체 unknown 반환
            return [
                ClassifyResult(
                    category_path="error/exception",
                    confidence=0.0,
                    reasoning=str(e),
                    model=f"{settings.CLAUDE_MODEL} (CLI)"
                )
                for _ in image_paths
            ]

    async def _run_cli(self, prompt: str, json_schema: dict) -> dict:
        """Claude CLI subprocess 실행 — stderr 실시간 스트리밍"""
        cmd = [
            self.cli_path,
            "-p", prompt,
            "--output-format", "json",
            "--json-schema", json.dumps(json_schema),
            "--allowedTools", "Read",  # 이미지 파일 읽기 허용
            "--model", settings.CLAUDE_MODEL
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # stderr 실시간 읽기 (CLI 진행 출력)
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

        # stderr 스트리밍과 stdout 수집을 병렬 실행
        stderr_task = asyncio.create_task(_stream_stderr())
        stdout_data = await proc.stdout.read()
        await stderr_task
        await proc.wait()

        if proc.returncode != 0:
            stderr_text = "\n".join(stderr_lines) if stderr_lines else "(no stderr)"
            raise RuntimeError(f"Claude CLI exit {proc.returncode}: {stderr_text}")

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

각 이미지 파일을 Read 도구로 읽어서 분석하고, 가장 적합한 카테고리를 선택하세요.
응답은 반드시 지정된 JSON 스키마 형식으로만 출력하세요.
"""

    def get_model_name(self) -> str:
        return f"{settings.CLAUDE_MODEL} (CLI)"

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
