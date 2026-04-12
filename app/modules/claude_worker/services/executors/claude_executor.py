"""ClaudeExecutor — Claude CLI subprocess 실행 전담."""

import json
import os
import subprocess
import sys
import tempfile

from app.modules.claude_worker.services.executors.base import LLMExecutorBase
from app.modules.claude_worker.services.profile_env import build_cli_env

QUOTA_PAUSE_DEFAULT_MS = 6 * 60 * 60 * 1000  # 6시간


def _parse_quota_retry_ms(text: str):
    """stderr/stdout에서 quota 재시도 대기 시간(ms) 파싱.

    1순위: retryDelayMs: 숫자 정규식 파싱
    2순위: reset after Xh Ym Zs 텍스트 파싱
    미감지: None 반환
    """
    import re
    if not text:
        return None

    # 1순위: retryDelayMs 파싱
    m = re.search(r"retryDelayMs:\s*([\d.]+)", text)
    if m:
        return int(float(m.group(1)))

    # 2순위: "reset after Xh Ym Zs" 파싱
    m = re.search(r"reset after (\d+)h(\d+)m(\d+)s", text)
    if m:
        h, mn, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return (h * 3600 + mn * 60 + s) * 1000

    return None


class ClaudeExecutor(LLMExecutorBase):
    """Claude CLI 실행 Executor.

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
        """Claude CLI 실행 (동기).

        Args:
            prompt: LLM 프롬프트
            model: 모델명 (빈 문자열이면 기본 모델 사용)
            timeout: 타임아웃 (초)
            parse_json: True면 JSON 파싱 시도, False면 raw_response만 반환
            enable_tools: True면 Read 도구 활성화 (이미지 분석 등)
            cli_options: CLI 옵션 dict (exec_mode, output_format, json_schema, allowed_tools, cwd 등)

        Returns:
            {"success": True, "result": {...}, "raw_response": "..."}
            또는
            {"success": False, "error": "..."}
        """
        if cli_options is None:
            cli_options = {}

        try:
            # 프롬프트를 임시 파일에 저장하여 전달 (긴 프롬프트 및 특수문자 처리)
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8"
            ) as f:
                f.write(prompt)
                prompt_file = f.name

            # Claude CLI 실행 env 조립 (profile 기반 config_dir 주입 포함)
            env = build_cli_env("claude")

            try:
                # cli_options 기반 명령어 빌드
                exec_mode = cli_options.get("exec_mode", False)
                output_format = cli_options.get("output_format")
                json_schema = cli_options.get("json_schema")
                allowed_tools = cli_options.get("allowed_tools")
                schema_file = None

                # cwd 처리 — 허용 경로 검증 후 subprocess cwd로 전달
                cwd_opt = cli_options.get("cwd")
                if cwd_opt:
                    import pathlib

                    ALLOWED_CWD_PREFIX = r"D:\work\project"
                    cwd_path = pathlib.Path(cwd_opt)
                    try:
                        cwd_path.relative_to(ALLOWED_CWD_PREFIX)
                    except ValueError:
                        raise ValueError(
                            f"허용되지 않은 cwd 경로: {cwd_opt} (허용: {ALLOWED_CWD_PREFIX} 하위만)"
                        )
                    if not cwd_path.exists():
                        raise ValueError(f"cwd 경로가 존재하지 않음: {cwd_opt}")
                    cwd_value = str(cwd_path)
                else:
                    cwd_value = None

                if exec_mode:
                    # ========== B 방식: exec 모드 ==========
                    # 이미지 분류 등 복잡한 CLI 옵션용.
                    schema_file_exec = None
                    try:
                        # json_schema → 임시파일
                        if json_schema:
                            schema_str = json.dumps(json_schema, ensure_ascii=False)
                            with tempfile.NamedTemporaryFile(
                                mode="w", suffix=".json", delete=False, encoding="utf-8"
                            ) as sf:
                                sf.write(schema_str)
                                schema_file_exec = sf.name
                            schema_opt = f'--json-schema "@{schema_file_exec}"'
                        else:
                            schema_opt = ""

                        # CLI 옵션 문자열 조립
                        tools_parts = []
                        if allowed_tools:
                            for tool in allowed_tools:
                                tools_parts.append(f"--allowedTools {tool}")
                        elif enable_tools:
                            tools_parts.append("--allowedTools Read")

                        model_opt = f"--model {model}" if model else ""
                        format_opt = f"--output-format {output_format}" if output_format else ""
                        opts = " ".join(
                            p for p in [*tools_parts, model_opt, format_opt, schema_opt] if p
                        )

                        # 프롬프트를 stdin으로 전달
                        if sys.platform == "win32":
                            cmd = f'type "{prompt_file}" | claude {opts}'
                        else:
                            cmd = f'cat "{prompt_file}" | claude {opts}'

                        result = subprocess.run(
                            cmd,
                            capture_output=True,
                            text=True,
                            timeout=timeout,
                            encoding="utf-8",
                            shell=True,
                            env=env,
                            cwd=cwd_value,
                        )
                    finally:
                        if schema_file_exec:
                            try:
                                os.unlink(schema_file_exec)
                            except Exception:
                                pass
                else:
                    # ========== A 방식: shell 모드 (stdin pipe, 2단계) ==========
                    if allowed_tools:
                        tools_opt = " ".join(f"--allowedTools {t}" for t in allowed_tools)
                    elif enable_tools:
                        tools_opt = '--tools "Read"'
                    else:
                        tools_opt = ""

                    model_opt = f"--model {model}" if model else ""
                    format_opt = f"--output-format {output_format}" if output_format else ""

                    # json schema: 임시파일로 전달
                    if json_schema:
                        schema_str = json.dumps(json_schema, ensure_ascii=False)
                        with tempfile.NamedTemporaryFile(
                            mode="w", suffix=".json", delete=False, encoding="utf-8"
                        ) as sf:
                            sf.write(schema_str)
                            schema_file = sf.name
                        if sys.platform == "win32":
                            schema_opt = f'--json-schema "$(type \\"{schema_file}\\")"'
                        else:
                            schema_opt = f"--json-schema '$(cat \"{schema_file}\")'"
                    else:
                        schema_opt = ""

                    opts = " ".join(
                        part for part in [tools_opt, model_opt, format_opt, schema_opt] if part
                    )

                    if sys.platform == "win32":
                        cmd = f'type "{prompt_file}" | claude {opts}'
                    else:
                        cmd = f'cat "{prompt_file}" | claude {opts}'

                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        encoding="utf-8",
                        shell=True,
                        env=env,
                        cwd=cwd_value,
                    )
            finally:
                os.unlink(prompt_file)
                if schema_file:
                    try:
                        os.unlink(schema_file)
                    except Exception:
                        pass

            if result.returncode != 0:
                error_details = result.stderr.strip() if result.stderr else ""
                if not error_details and result.stdout:
                    error_details = result.stdout.strip()[:500]
                if not error_details:
                    error_details = f"returncode={result.returncode}"

                combined_output = (result.stderr or "") + (result.stdout or "")
                quota_keywords = ["overloaded_error", "rate_limit_error"]
                if any(kw in combined_output for kw in quota_keywords):
                    retry_ms = _parse_quota_retry_ms(combined_output)
                    if retry_ms is None:
                        retry_ms = QUOTA_PAUSE_DEFAULT_MS
                    return {
                        "success": False,
                        "error": f"Claude CLI error: {error_details}",
                        "quota_retry_ms": retry_ms,
                    }

                return {"success": False, "error": f"Claude CLI error: {error_details}"}

            raw_response = result.stdout.strip()

            # --output-format json + --json-schema 사용 시 structured_output 파싱
            if output_format == "json" and json_schema:
                try:
                    raw_json = json.loads(raw_response)
                    if "structured_output" in raw_json and raw_json["structured_output"]:
                        return {
                            "success": True,
                            "result": raw_json["structured_output"],
                            "raw_response": raw_response,
                        }
                    result_field = raw_json.get("result", "")
                    if isinstance(result_field, dict):
                        return {
                            "success": True,
                            "result": result_field,
                            "raw_response": raw_response,
                        }
                    if isinstance(result_field, str) and result_field.strip().startswith("{"):
                        try:
                            return {
                                "success": True,
                                "result": json.loads(result_field),
                                "raw_response": raw_response,
                            }
                        except json.JSONDecodeError:
                            pass
                    return {
                        "success": False,
                        "error": f"structured_output/result 필드 없음. raw: {str(raw_json)[:200]}",
                        "raw_response": raw_response,
                    }
                except json.JSONDecodeError as e:
                    return {
                        "success": False,
                        "error": f"structured output JSON 파싱 실패: {e}",
                        "raw_response": raw_response,
                    }

            # JSON 파싱 (선택적)
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
                "error": "Claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
