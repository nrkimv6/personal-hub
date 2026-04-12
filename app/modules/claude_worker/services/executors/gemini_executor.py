"""GeminiExecutor — Gemini CLI subprocess 실행 전담."""

import os
import subprocess
import sys
import tempfile

from app.modules.claude_worker.services.executors.base import LLMExecutorBase
from app.modules.claude_worker.services.profile_env import build_cli_env

QUOTA_PAUSE_DEFAULT_MS = 60_000


def _parse_quota_retry_ms(output: str):
    """quota 에러 응답에서 retry_after_ms 추출. 없으면 None."""
    import re

    m = re.search(r'"retry_after_ms"\s*:\s*(\d+)', output)
    return int(m.group(1)) if m else None


class GeminiExecutor(LLMExecutorBase):
    """Gemini CLI 실행 Executor.

    DB 접근 없음 — subprocess 호출과 결과 파싱만 담당.
    """

    def execute(
        self,
        prompt: str,
        *,
        model: str = "",
        timeout: int = 120,
        parse_json: bool = True,
        enable_tools: bool = False,
        cli_options: dict = None,
    ) -> dict:
        """Gemini CLI 실행 (동기).

        Args:
            prompt: LLM 프롬프트
            model: 모델명 (빈 문자열이면 기본 모델 사용)
            timeout: 타임아웃 (초)
            parse_json: True면 JSON 파싱 시도, False면 raw_response만 반환
            enable_tools: True면 파일 도구 활성화 (Gemini는 built-in으로 지원)
            cli_options: CLI 옵션 dict. 현재 지원: image_path (str)

        Returns:
            {"success": True, "result": {...}, "raw_response": "..."}
            또는
            {"success": False, "error": "..."}
        """
        try:
            # 프롬프트를 임시 파일에 저장하여 전달
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8"
            ) as f:
                f.write(prompt)
                prompt_file = f.name

            # Gemini CLI 실행 env 조립 (profile 기반 config_dir 주입 포함)
            env = build_cli_env("gemini")

            try:
                model_opt = f"--model {model}" if model else ""

                # image_path가 있으면 @경로 이미지 첨부 인수 구성
                image_path = (cli_options or {}).get("image_path")
                img_arg = f' @"{image_path}"' if image_path else ""

                if sys.platform == "win32":
                    cmd = f'type "{prompt_file}" | gemini {model_opt}{img_arg}'
                else:
                    cmd = f'cat "{prompt_file}" | gemini {model_opt}{img_arg}'

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    encoding="utf-8",
                    shell=True,
                    env=env,
                )
            finally:
                os.unlink(prompt_file)

            if result.returncode != 0:
                error_details = result.stderr.strip() if result.stderr else ""
                if not error_details and result.stdout:
                    error_details = result.stdout.strip()[:500]
                if not error_details:
                    error_details = f"returncode={result.returncode}"

                combined_output = (result.stderr or "") + (result.stdout or "")
                quota_keywords = ["TerminalQuotaError", "exhausted your capacity"]
                if any(kw in combined_output for kw in quota_keywords):
                    retry_ms = _parse_quota_retry_ms(combined_output)
                    if retry_ms is None:
                        retry_ms = QUOTA_PAUSE_DEFAULT_MS
                    return {
                        "success": False,
                        "error": f"Gemini CLI error: {error_details}",
                        "quota_retry_ms": retry_ms,
                    }

                return {"success": False, "error": f"Gemini CLI error: {error_details}"}

            raw_response = result.stdout.strip()

            if parse_json:
                try:
                    parsed = self._parse_json_response(raw_response)
                    return {"success": True, "result": parsed, "raw_response": raw_response}
                except ValueError as e:
                    return {
                        "success": False,
                        "error": f"JSON 파싱 실패: {e}",
                        "raw_response": raw_response,
                    }
            else:
                return {"success": True, "result": None, "raw_response": raw_response}

        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"Timeout ({timeout}s)"}
        except FileNotFoundError:
            return {
                "success": False,
                "error": "Gemini CLI not found. Install with: npm install -g @google/generative-ai-cli",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
