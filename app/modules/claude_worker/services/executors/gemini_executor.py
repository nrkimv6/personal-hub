"""GeminiExecutor — Gemini CLI subprocess 실행 전담."""

import subprocess

from app.modules.claude_worker.services.executors.base import LLMExecutorBase
from app.modules.claude_worker.services.executors.claude_executor import _parse_quota_retry_ms
from app.modules.claude_worker.services.profile_env import build_cli_env

QUOTA_PAUSE_DEFAULT_MS = 6 * 60 * 60 * 1000  # 6시간


def _build_gemini_command(*, model: str, image_path: str | None) -> list[str]:
    command = ["gemini"]
    if model:
        command.extend(["--model", model])
    if image_path:
        command.append(f"@{image_path}")
    return command


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
        profile=None,
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
            # Gemini CLI 실행 env 조립 (profile 기반 config_dir 주입 포함)
            env = build_cli_env("gemini", profile=profile)

            image_path = (cli_options or {}).get("image_path")
            command = _build_gemini_command(model=model, image_path=image_path)
            result = subprocess.run(
                command,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
                shell=False,
                env=env,
            )

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
